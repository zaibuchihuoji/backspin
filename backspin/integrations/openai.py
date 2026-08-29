"""Capture OpenAI-SDK-shaped chat completion calls into a Recorder.

The wrapper duck-types: it works with the real ``openai.OpenAI`` /
``openai.AsyncOpenAI`` clients and with any object shaped like them (see
:mod:`backspin.testing`), sync or async, streaming or not.
"""
from __future__ import annotations

import functools
import inspect
import time
from typing import Any, Callable, Dict, List, Optional

from ..fakes import stream_chunks  # noqa: F401  (re-exported for replay/tests)
from ..runfile import jsonable

# Request fields worth keeping in a recording. Everything else (clients,
# callables, ...) is dropped rather than repr-ed to keep run files clean.
_KEEP = {
    "model",
    "messages",
    "tools",
    "tool_choice",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "n",
    "stream",
    "stream_options",
    "response_format",
    "seed",
    "user",
    "metadata",
    "frequency_penalty",
    "presence_penalty",
    "parallel_tool_calls",
    "logprobs",
    "top_logprobs",
}


def _clean_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: jsonable(v) for k, v in kwargs.items() if k in _KEEP}


def _usage_of(usage: Any) -> Optional[Dict[str, Any]]:
    """Extract a dict from a usage object/dict of any shape."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump(exclude_none=True)
        except TypeError:
            return usage.model_dump()
    return {
        k: getattr(usage, k)
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if getattr(usage, k, None) is not None
    }


def _usage(resp: Any) -> Optional[Dict[str, Any]]:
    return _usage_of(getattr(resp, "usage", None))


def _response_payload(resp: Any) -> Dict[str, Any]:
    if hasattr(resp, "model_dump"):
        try:
            return resp.model_dump(exclude_none=True)
        except TypeError:
            return resp.model_dump()
    return {"repr": repr(resp)}


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


class _StreamState:
    """Accumulated view of a streamed completion, built from its chunks."""

    def __init__(self) -> None:
        self.content: List[str] = []
        self.tool_calls: Dict[int, Dict[str, Any]] = {}
        self.model: Optional[str] = None
        self.usage: Optional[Dict[str, Any]] = None
        self.finish_reason: Optional[str] = None

    def absorb(self, chunk: Any) -> None:
        model = getattr(chunk, "model", None)
        if model:
            self.model = model
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self.usage = _usage_of(usage)
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if content:
                self.content.append(content)
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0)
                slot = self.tool_calls.setdefault(
                    idx,
                    {"id": "", "type": "function",
                     "function": {"name": "", "arguments": ""}},
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["function"]["arguments"] += fn.arguments
            finish = getattr(choice, "finish_reason", None)
            if finish:
                self.finish_reason = finish

    def payload(self) -> Dict[str, Any]:
        message: Dict[str, Any] = {"role": "assistant"}
        if self.content:
            message["content"] = "".join(self.content)
        if self.tool_calls:
            message["tool_calls"] = [self.tool_calls[i] for i in sorted(self.tool_calls)]
        return {
            "object": "chat.completion",
            "model": self.model,
            "reconstructed_from_stream": True,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": self.finish_reason or "stop",
                    "message": message,
                }
            ],
            "usage": self.usage,
        }


def capture_openai(recorder: Any, client: Any) -> Any:
    """Patch ``client.chat.completions.create`` to record every call."""
    completions = client.chat.completions
    original = completions.create
    # Newer openai SDKs ship async methods that are not coroutine functions
    # (they return awaitables), so the resource type name is the reliable tell.
    is_async = inspect.iscoroutinefunction(original) or type(
        completions
    ).__name__.lower().startswith("async")
    if is_async:
        completions.create = _async_wrapper(recorder, original)
    else:
        completions.create = _sync_wrapper(recorder, original)
    return client


def _sync_wrapper(recorder: Any, original: Callable) -> Callable:
    @functools.wraps(original)
    def create(*args: Any, **kwargs: Any):
        t0 = time.perf_counter()
        try:
            resp = original(*args, **kwargs)
        except Exception as exc:
            recorder.record_llm(
                request=_clean_kwargs(kwargs),
                model=kwargs.get("model"),
                error=exc,
                duration_ms=_ms(t0),
            )
            raise
        if kwargs.get("stream"):
            return _StreamRecorder(recorder, kwargs, resp, t0)
        recorder.record_llm(
            request=_clean_kwargs(kwargs),
            response=_response_payload(resp),
            usage=_usage(resp),
            model=kwargs.get("model") or getattr(resp, "model", None),
            duration_ms=_ms(t0),
        )
        return resp

    return create


def _async_wrapper(recorder: Any, original: Callable) -> Callable:
    @functools.wraps(original)
    async def create(*args: Any, **kwargs: Any):
        t0 = time.perf_counter()
        try:
            resp = await original(*args, **kwargs)
        except Exception as exc:
            recorder.record_llm(
                request=_clean_kwargs(kwargs),
                model=kwargs.get("model"),
                error=exc,
                duration_ms=_ms(t0),
            )
            raise
        if kwargs.get("stream"):
            return _AsyncStreamRecorder(recorder, kwargs, resp, t0)
        recorder.record_llm(
            request=_clean_kwargs(kwargs),
            response=_response_payload(resp),
            usage=_usage(resp),
            model=kwargs.get("model") or getattr(resp, "model", None),
            duration_ms=_ms(t0),
        )
        return resp

    return create


class _StreamRecorder:
    """Transparent iterator wrapper: passthrough chunks, record on end."""

    def __init__(self, recorder: Any, kwargs: Dict[str, Any], stream: Any, t0: float):
        self._recorder = recorder
        self._kwargs = kwargs
        self._stream = stream
        self._t0 = t0
        self._state = _StreamState()
        self._done = False

    def __iter__(self) -> "_StreamRecorder":
        return self

    def __next__(self) -> Any:
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._finalize()
            raise
        except Exception as exc:
            self._finalize(error=exc)
            raise
        self._state.absorb(chunk)
        return chunk

    def close(self) -> None:
        closer = getattr(self._stream, "close", None)
        if closer is not None:
            closer()
        self._finalize()

    def __enter__(self) -> "_StreamRecorder":
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, *exc_info: Any):
        try:
            self._finalize()
        finally:
            exit_ = getattr(self._stream, "__exit__", None)
            if exit_ is not None:
                return exit_(*exc_info)
        return None

    def _finalize(self, error: Optional[BaseException] = None) -> None:
        if self._done:
            return
        self._done = True
        self._recorder.record_llm(
            request=_clean_kwargs(self._kwargs),
            response=self._state.payload(),
            usage=self._state.usage,
            model=self._kwargs.get("model") or self._state.model,
            duration_ms=_ms(self._t0),
            error=error,
        )


class _AsyncStreamRecorder(_StreamRecorder):
    def __aiter__(self) -> "_AsyncStreamRecorder":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finalize()
            raise
        except Exception as exc:
            self._finalize(error=exc)
            raise
        self._state.absorb(chunk)
        return chunk

    async def aclose(self) -> None:
        closer = getattr(self._stream, "aclose", None)
        if closer is not None:
            await closer()
        self._finalize()

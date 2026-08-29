"""Capture Anthropic-SDK-shaped messages.create calls into a Recorder.

Duck-typed like the OpenAI integration: works with the real
``anthropic.Anthropic`` / ``anthropic.AsyncAnthropic`` clients and anything
shaped the same (see :mod:`backspin.testing`).

Anthropic events are recorded as ``kind="llm"`` with ``provider="anthropic"``
and the native request/response payloads preserved; ``usage`` is normalized
to ``prompt_tokens``/``completion_tokens`` so cost estimation and diffs work
across providers.
"""
from __future__ import annotations

import functools
import inspect
import time
from typing import Any, Callable, Dict, List, Optional

from ..runfile import jsonable

_KEEP = {
    "model", "messages", "system", "max_tokens", "tools", "tool_choice",
    "temperature", "top_p", "top_k", "stream", "metadata", "stop_sequences",
}


def _clean_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: jsonable(v) for k, v in kwargs.items() if k in _KEEP}


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def _usage_of(usage: Any) -> Optional[Dict[str, Any]]:
    """Normalize anthropic usage {input_tokens, output_tokens} for cost."""
    if usage is None:
        return None
    get = usage.get if isinstance(usage, dict) else lambda k: getattr(usage, k, None)
    prompt = get("input_tokens")
    completion = get("output_tokens")
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": prompt or 0,
        "completion_tokens": completion or 0,
        "input_tokens": prompt or 0,
        "output_tokens": completion or 0,
    }


def _response_payload(resp: Any) -> Dict[str, Any]:
    if hasattr(resp, "model_dump"):
        try:
            return resp.model_dump(exclude_none=True)
        except TypeError:
            return resp.model_dump()
    return {"repr": repr(resp)}


class _Acc:
    """Accumulated view of a streamed anthropic message."""

    def __init__(self, fallback_model: Optional[str]) -> None:
        self.model = fallback_model
        self.blocks: Dict[int, Dict[str, Any]] = {}
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.stop_reason: Optional[str] = None

    def absorb(self, event: Any) -> None:
        data = event.model_dump() if hasattr(event, "model_dump") else event
        if not isinstance(data, dict):
            return
        etype = data.get("type")
        if etype == "message_start":
            message = data.get("message") or {}
            if message.get("model"):
                self.model = message["model"]
            usage = _usage_of(message.get("usage"))
            if usage:
                self.input_tokens = usage["prompt_tokens"]
        elif etype == "content_block_start":
            block = data.get("content_block") or {}
            self.blocks[data.get("index", 0)] = dict(block)
        elif etype == "content_block_delta":
            block = self.blocks.setdefault(data.get("index", 0), {"type": "text", "text": ""})
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                block["type"] = "text"
                block["text"] = block.get("text", "") + (delta.get("text") or "")
            elif delta.get("type") == "input_json_delta":
                block["type"] = "tool_use"
                block["partial_json"] = block.get("partial_json", "") + (delta.get("partial_json") or "")
        elif etype == "message_delta":
            stop = (data.get("delta") or {}).get("stop_reason")
            if stop:
                self.stop_reason = stop
            usage = _usage_of(data.get("usage"))
            if usage:
                self.output_tokens = usage["completion_tokens"]

    def payload(self) -> Dict[str, Any]:
        content = []
        for idx in sorted(self.blocks):
            block = dict(self.blocks[idx])
            if block.get("type") == "tool_use" and block.get("partial_json"):
                import json as _json

                try:
                    block["input"] = _json.loads(block.pop("partial_json"))
                except ValueError:
                    block["input"] = block.pop("partial_json")
            content.append(block)
        usage: Dict[str, Any] = {}
        if self.input_tokens is not None:
            usage["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            usage["output_tokens"] = self.output_tokens
        return {
            "object": "anthropic.message",
            "reconstructed_from_stream": True,
            "model": self.model,
            "role": "assistant",
            "content": content,
            "stop_reason": self.stop_reason,
            "usage": usage or None,
        }


def capture_anthropic(recorder: Any, client: Any) -> Any:
    """Patch ``client.messages.create`` so every call is recorded."""
    messages = client.messages
    original = messages.create
    is_async = inspect.iscoroutinefunction(original) or type(
        messages
    ).__name__.lower().startswith("async")
    if is_async:
        messages.create = _async_wrapper(recorder, original)
    else:
        messages.create = _sync_wrapper(recorder, original)
    return client


def _record(recorder: Any, kwargs: Dict[str, Any], *, response: Any = None,
            usage: Any = None, error: Any = None, duration_ms: float,
            model: Any = None) -> None:
    recorder.record_llm(
        request=_clean_kwargs(kwargs),
        response=response,
        usage=usage,
        error=error,
        duration_ms=duration_ms,
        model=model or kwargs.get("model"),
        provider="anthropic",
    )


def _sync_wrapper(recorder: Any, original: Callable) -> Callable:
    @functools.wraps(original)
    def create(*args: Any, **kwargs: Any):
        t0 = time.perf_counter()
        try:
            resp = original(*args, **kwargs)
        except Exception as exc:
            _record(recorder, kwargs, error=exc, duration_ms=_ms(t0))
            raise
        if kwargs.get("stream"):
            return _StreamRecorder(recorder, kwargs, resp, t0)
        usage = _usage_of(getattr(resp, "usage", None))
        _record(recorder, kwargs, response=_response_payload(resp), usage=usage,
                duration_ms=_ms(t0), model=getattr(resp, "model", None))
        return resp

    return create


def _async_wrapper(recorder: Any, original: Callable) -> Callable:
    @functools.wraps(original)
    async def create(*args: Any, **kwargs: Any):
        t0 = time.perf_counter()
        try:
            resp = await original(*args, **kwargs)
        except Exception as exc:
            _record(recorder, kwargs, error=exc, duration_ms=_ms(t0))
            raise
        if kwargs.get("stream"):
            return _AsyncStreamRecorder(recorder, kwargs, resp, t0)
        usage = _usage_of(getattr(resp, "usage", None))
        _record(recorder, kwargs, response=_response_payload(resp), usage=usage,
                duration_ms=_ms(t0), model=getattr(resp, "model", None))
        return resp

    return create


class _StreamRecorder:
    """Transparent iterator over anthropic stream events, recorded at end."""

    def __init__(self, recorder: Any, kwargs: Dict[str, Any], stream: Any, t0: float):
        self._recorder = recorder
        self._kwargs = kwargs
        self._stream = stream
        self._t0 = t0
        self._acc = _Acc(kwargs.get("model"))
        self._done = False

    def __iter__(self) -> "_StreamRecorder":
        return self

    def __next__(self) -> Any:
        try:
            event = next(self._stream)
        except StopIteration:
            self._finalize()
            raise
        except Exception as exc:
            self._finalize(error=exc)
            raise
        self._acc.absorb(event)
        return event

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
        acc = self._acc
        usage = None
        if acc.input_tokens is not None or acc.output_tokens is not None:
            usage = {"prompt_tokens": acc.input_tokens or 0,
                     "completion_tokens": acc.output_tokens or 0}
        _record(
            self._recorder, self._kwargs,
            response=acc.payload(), usage=usage, error=error,
            duration_ms=_ms(self._t0), model=acc.model,
        )


class _AsyncStreamRecorder(_StreamRecorder):
    def __aiter__(self) -> "_AsyncStreamRecorder":
        return self

    async def __anext__(self) -> Any:
        try:
            event = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finalize()
            raise
        except Exception as exc:
            self._finalize(error=exc)
            raise
        self._acc.absorb(event)
        return event

    async def aclose(self) -> None:
        closer = getattr(self._stream, "aclose", None)
        if closer is not None:
            await closer()
        self._finalize()

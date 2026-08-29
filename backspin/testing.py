"""Scripted OpenAI-shaped clients for demos, tests, and offline dev.

``FakeOpenAI`` answers ``chat.completions.create`` from a script of
responses — strings become assistant messages. Pair it with
``Recorder.capture_openai`` to build runnable examples without an API key,
or use it in your own test suite to pin agent behavior.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Union

from .fakes import FakeResponse, message_data, stream_chunks


def _normalize(responses: Iterable[Union[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in responses:
        if isinstance(r, str):
            out.append(message_data(r))
        else:
            out.append(r)
    return out


class _BaseFake:
    def __init__(self, responses: Iterable[Union[str, Dict[str, Any]]]):
        self.script = _normalize(responses)
        self.calls: List[Dict[str, Any]] = []

    def _answer(self, kwargs: Dict[str, Any]):
        i = len(self.calls)
        self.calls.append(kwargs)
        data = dict(self.script[i]) if i < len(self.script) else message_data("")
        data.setdefault("model", kwargs.get("model", "fake-model"))
        data.setdefault(
            "usage", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        if kwargs.get("stream"):
            return iter(stream_chunks(data))
        return FakeResponse(data)


class FakeOpenAI(_BaseFake):
    """Sync stand-in for ``openai.OpenAI``."""

    def __init__(self, responses: Iterable[Union[str, Dict[str, Any]]]):
        super().__init__(responses)
        from types import SimpleNamespace

        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **kwargs: Any):
        return self._answer(kwargs)


class FakeAsyncOpenAI(_BaseFake):
    """Async stand-in for ``openai.AsyncOpenAI``."""

    def __init__(self, responses: Iterable[Union[str, Dict[str, Any]]]):
        super().__init__(responses)
        from types import SimpleNamespace

        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    async def _create(self, **kwargs: Any):
        return self._answer(kwargs)


class FakeAnthropic:
    """Scripted stand-in for ``anthropic.Anthropic`` (messages.create).

    Responses are strings (assistant text), dicts (raw message payloads), or
    None (defaults to a minimal text message).
    """

    def __init__(self, responses: Iterable[Union[str, Dict[str, Any], None]]):
        from types import SimpleNamespace

        self.script: List[Any] = list(responses)
        self.calls: List[Dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    @staticmethod
    def _message_data(text: str) -> Dict[str, Any]:
        return {
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "model": "fake-claude",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 8, "output_tokens": 4},
        }

    def _create(self, **kwargs: Any):
        i = len(self.calls)
        self.calls.append(kwargs)
        raw = self.script[i] if i < len(self.script) else None
        if isinstance(raw, str):
            data = self._message_data(raw)
        else:
            data = dict(raw or self._message_data(""))
        data.setdefault("model", kwargs.get("model", "fake-claude"))
        data.setdefault(
            "usage", {"input_tokens": 8, "output_tokens": 4}
        )
        from .fakes import FakeAnthropicMessage

        return FakeAnthropicMessage(data)


class FakeAsyncAnthropic(FakeAnthropic):
    """Async stand-in for ``anthropic.AsyncAnthropic``."""

    def __init__(self, responses: Iterable[Union[str, Dict[str, Any], None]]):
        super().__init__(responses)

    async def acreate(self, **kwargs: Any):  # convenience for async-style tests
        return self._create(**kwargs)

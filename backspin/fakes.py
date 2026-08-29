"""Duck-typed fakes for the slice of the OpenAI SDK that backspin records.

Used by :mod:`backspin.testing` (scripted clients for demos and your own
tests) and by :mod:`backspin.replay` (replaying recordings without the SDK).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional


def _ns(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_ns(x) for x in obj]
    return obj


def message_data(content: Optional[str], *, role: str = "assistant",
                 tool_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Build a completion-shaped dict from just an assistant message."""
    msg: Dict[str, Any] = {"role": role, "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class FakeResponse:
    """Stands in for ``openai``'s ChatCompletion."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.id = data.get("id", "chatcmpl-fake")
        self.object = data.get("object", "chat.completion")
        self.model = data.get("model", "fake-model")
        self.choices = _ns(data.get("choices", []))
        usage = data.get("usage")
        self.usage = _ns(usage) if usage else None

    def model_dump(self, **_kw: Any) -> Dict[str, Any]:
        return self._data


class FakeChunk:
    """Stands in for one ``openai`` ChatCompletionChunk in streaming mode."""

    def __init__(self, *, model: str, delta: Optional[Dict[str, Any]] = None,
                 finish_reason: Optional[str] = None, usage: Optional[Dict] = None):
        self.model = model
        self.object = "chat.completion.chunk"
        delta = dict(delta or {})
        delta.setdefault("content", None)
        self.choices = [
            SimpleNamespace(index=0, delta=_ns(delta), finish_reason=finish_reason)
        ]
        self.usage = usage

    def model_dump(self, **_kw: Any) -> Dict[str, Any]:
        return {
            "model": self.model,
            "object": self.object,
            "choices": [
                {
                    "index": 0,
                    "delta": self.choices[0].delta.__dict__,
                    "finish_reason": self.choices[0].finish_reason,
                }
            ],
            "usage": self.usage,
        }


def stream_chunks(data: Dict[str, Any], pieces: int = 3) -> Iterator[FakeChunk]:
    """Turn a completion-shaped dict into an iterable of chunk-like objects."""
    model = data.get("model", "fake-model")
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        yield FakeChunk(model=model, delta={"role": "assistant", "tool_calls": tool_calls})
    if content:
        step = max(1, len(content) // pieces)
        for i in range(0, len(content), step):
            yield FakeChunk(model=model, delta={"content": content[i : i + step]})
    yield FakeChunk(model=model, finish_reason="stop", usage=data.get("usage"))

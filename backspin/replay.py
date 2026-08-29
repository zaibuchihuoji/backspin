"""Deterministic replay: run your agent again with recorded LLM responses.

A :class:`Cassette` indexes the LLM calls of a recorded run. A stub client
answers new calls from the cassette, matching by request fingerprint
(model + messages) and falling back to call order — so you can re-run the
agent offline, in tests, or against a fix, with the LLM held constant.
"""
from __future__ import annotations

import warnings
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from .fakes import FakeResponse, stream_chunks
from .runfile import Run, fingerprint_request


class ReplayMismatchWarning(UserWarning):
    """A replayed request did not exactly match its recording."""


class ReplayMismatch(Exception):
    """The cassette ran out of recordings before the replay finished."""


class Cassette:
    """Indexed recordings of LLM calls from one run."""

    def __init__(self, entries: List[Dict[str, Any]]):
        self.entries = entries
        self._cursor = 0

    @classmethod
    def from_run(cls, run: Run) -> "Cassette":
        return cls([e for e in run.llm_calls() if e.get("response") is not None])

    def __len__(self) -> int:
        return len(self.entries)

    def match(self, fingerprint: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Best-effort match against the remaining tape: exact fingerprint
        first, then the next recording in call order.

        Returns ``(entry, exact)``. ``entry`` is ``None`` when the cassette
        is exhausted. Matching is sequential — each recording is consumed
        at most once, so looping agents surface as exhaustion instead of
        silently looping the same response forever.
        """
        for i in range(self._cursor, len(self.entries)):
            if self.entries[i].get("fingerprint") == fingerprint:
                self._cursor = i + 1
                return self.entries[i], True
        if self._cursor < len(self.entries):
            entry = self.entries[self._cursor]
            self._cursor += 1
            return entry, False
        return None, False

    def take(self, fingerprint: str) -> Dict[str, Any]:
        """Like :meth:`match` but raises on exhaustion and warns on fallback."""
        entry, exact = self.match(fingerprint)
        if entry is None:
            raise ReplayMismatch(
                f"no recording left in cassette (wanted fingerprint {fingerprint})"
            )
        if not exact:
            warnings.warn(
                f"request fingerprint {fingerprint} not in cassette; "
                f"falling back to recording #{self._cursor} by call order",
                ReplayMismatchWarning,
                stacklevel=3,
            )
        return entry


class _StubCompletions:
    """Duck-typed ``chat.completions`` answered from a cassette."""

    def __init__(self, cassette: Cassette, *, async_mode: bool = False):
        self.cassette = cassette
        self.state = SimpleNamespace(calls=0, mismatches=[])
        self._async = async_mode

    def _respond(self, **kwargs: Any):
        self.state.calls += 1
        fp = fingerprint_request(kwargs.get("model"), kwargs.get("messages"))
        entry, exact = self.cassette.match(fp)
        if entry is None:
            raise ReplayMismatch(
                f"LLM call #{self.state.calls}: cassette exhausted "
                f"(fingerprint={fp})"
            )
        if not exact:
            self.state.mismatches.append(
                {"call": self.state.calls, "requested": fp,
                 "replayed": entry.get("fingerprint")}
            )
            warnings.warn(
                f"LLM call #{self.state.calls}: fingerprint mismatch, "
                f"replaying recording #{self.cassette._cursor} by call order",
                ReplayMismatchWarning,
                stacklevel=2,
            )
        data = dict(entry["response"])
        if kwargs.get("stream"):
            return iter(stream_chunks(data))
        return FakeResponse(data)

    def create(self, **kwargs: Any):
        if self._async:
            return self._respond_async(**kwargs)
        return self._respond(**kwargs)

    async def _respond_async(self, **kwargs: Any):
        return self._respond(**kwargs)


def stub_client(cassette: Cassette, *, async_mode: bool = False) -> SimpleNamespace:
    """A client shaped like ``openai.OpenAI`` (the slice agents touch)."""
    completions = _StubCompletions(cassette, async_mode=async_mode)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions), state=completions.state
    )


@contextmanager
def patch_openai(cassette: Cassette):
    """Patch ``openai.OpenAI`` / ``openai.AsyncOpenAI`` so constructors
    yield stub clients backed by ``cassette``. Restores on exit.

    Lets unmodified agent code (``client = OpenAI()``) replay offline.
    """
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "patch_openai() requires the openai package: pip install openai"
        ) from exc
    saved = (openai.OpenAI, openai.AsyncOpenAI)
    sync_client = stub_client(cassette)
    async_client = stub_client(cassette, async_mode=True)
    openai.OpenAI = lambda *a, **k: sync_client
    openai.AsyncOpenAI = lambda *a, **k: async_client
    try:
        yield SimpleNamespace(sync=sync_client, async_=async_client)
    finally:
        openai.OpenAI, openai.AsyncOpenAI = saved

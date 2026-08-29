"""pytest integration: one fixture for deterministic agent testing.

Activated automatically when backspin is installed (pytest11 entry point)::

    def test_my_agent(backspin):
        client = FakeOpenAI(["answer"])          # or a real OpenAI client
        with backspin.record(agent="t") as rec:
            run_agent(rec.capture_openai(client))
        backspin.assert_replays_identically()    # the run must replay clean

``assert_replays_identically()`` loads the recording, replays every LLM
call through its cassette and fails the test on any mismatch — catching
corrupted runs and broken fingerprints before they ship.
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

from . import Cassette, Recorder, load_run
from .replay import ReplayMismatch, stub_client


class _BackspinFixture:
    """Recorder factory + replay assertions, scoped to the test's tmp dir."""

    def __init__(self, tmp_path):
        self._tmp = tmp_path
        self._rec: Optional[Recorder] = None

    def record(self, agent: str = "test", **kwargs: Any) -> Recorder:
        self._rec = Recorder(dir=str(self._tmp), agent=agent, **kwargs)
        return self._rec

    @property
    def path(self) -> Optional[str]:
        return self._rec.path if self._rec is not None else None

    def assert_replays_identically(self, rec: Optional[Recorder] = None) -> None:
        """Every LLM call in the recording must replay through its cassette.

        Strict: each call must match a recording by exact request
        fingerprint — order fallbacks are failures, because they mean the
        run is not deterministically replayable.
        """
        rec = rec or self._rec
        if rec is None:
            raise AssertionError("no recording: call backspin.record() first")
        run = load_run(rec.path)
        cassette = Cassette.from_run(run)
        stub = stub_client(cassette)
        for event in run.llm_calls():
            request = dict(event.get("request") or {})
            try:
                resp = stub.chat.completions.create(
                    model=event.get("model"),
                    messages=request.get("messages"),
                )
            except ReplayMismatch as exc:
                raise AssertionError(
                    f"step #{event.get('seq')} is not replayable: {exc}"
                ) from exc
            dumped = resp.model_dump()
            recorded = (event.get("response") or {}).get("choices") or [{}]
            replayed = dumped.get("choices") or [{}]
            if recorded[0].get("message") != replayed[0].get("message"):
                raise AssertionError(
                    f"step #{event.get('seq')} replays with a different message"
                )
        mismatches = stub.chat.completions.state.mismatches
        if mismatches:
            raise AssertionError(
                f"{len(mismatches)} LLM call(s) replayed by call-order fallback "
                "instead of exact fingerprint match — the run is not "
                "deterministically replayable (steps: "
                + ", ".join(str(m["call"]) for m in mismatches) + ")"
            )


@pytest.fixture
def backspin(tmp_path):
    return _BackspinFixture(tmp_path)

"""The pytest plugin: fixture, recording, replay assertions."""
import pytest

from backspin.testing import FakeOpenAI


def test_backspin_fixture_records_and_asserts(backspin):
    with backspin.record(agent="plugin-test") as rec:
        client = rec.capture_openai(FakeOpenAI(["a1", "a2"]))
        client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "one"}]
        )
        client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "two"}]
        )
    assert rec.path
    backspin.assert_replays_identically()  # must not raise


def test_backspin_fixture_detects_tampered_run(backspin):
    import json
    from pathlib import Path

    with backspin.record(agent="plugin-test") as rec:
        client = rec.capture_openai(FakeOpenAI(["a1"]))
        client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "one"}]
        )
    # tamper: append a ghost LLM call the cassette cannot answer, so replay
    # must fail with exhaustion
    path = Path(rec.path)
    lines = path.read_text(encoding="utf-8").splitlines()
    ghost = {
        "kind": "llm", "seq": 99, "ts": 0.0, "model": "m",
        "duration_ms": 0.0, "fingerprint": "ffffffffffffffff",
        "request": {"model": "m", "messages": [{"role": "user", "content": "ghost"}]},
        "response": {"choices": [{"message": {"role": "assistant", "content": "?"}}]},
    }
    lines.append(json.dumps(ghost, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        backspin.assert_replays_identically()


def test_assert_without_record_raises(backspin):
    with pytest.raises(AssertionError):
        backspin.assert_replays_identically()

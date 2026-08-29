import asyncio

import pytest

from backspin import Recorder, load_run


class _BrokenFP:
    """Stand-in for a run file that can no longer be written (disk full)."""

    def write(self, s):
        raise OSError("simulated disk full")

    def flush(self):
        raise OSError("simulated disk full")

    def close(self):
        pass


def test_log_llm_tool(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.log("hello")
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            response={"x": 1},
            duration_ms=5.0,
            usage={"prompt_tokens": 1, "completion_tokens": 2},
        )

        @rec.tool
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    run = load_run(rec.path)
    assert [e["kind"] for e in run.events] == ["log", "llm", "tool"]
    assert [e["seq"] for e in run.events] == [1, 2, 3]
    llm = run.events[1]
    assert llm["model"] == "m"
    assert llm["fingerprint"]
    assert llm["usage"]["completion_tokens"] == 2
    tool = run.events[2]
    assert tool["name"] == "add"
    assert tool["result"] == 3
    assert tool["args"] == {"args": [1, 2], "kwargs": {}}


def test_error_recorded_and_reraised(tmp_path):
    with pytest.raises(RuntimeError), Recorder(dir=str(tmp_path), agent="bot") as rec:
        raise RuntimeError("boom")
    run = load_run(rec.path)
    ev = run.events[-1]
    assert ev["kind"] == "error"
    assert ev["error_type"] == "RuntimeError"
    assert "boom" in ev["traceback"]


def test_tool_error_recorded(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:

        @rec.tool
        def explode():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            explode()

    tool = load_run(rec.path).tool_calls()[0]
    assert tool["error"] == "nope"


def test_async_tool(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:

        @rec.tool
        async def ping():
            return "pong"

        assert asyncio.run(ping()) == "pong"

    assert load_run(rec.path).tool_calls()[0]["result"] == "pong"


def test_custom_event(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.event("guardrail", verdict="blocked")
    ev = load_run(rec.path).events[0]
    assert ev["kind"] == "guardrail"
    assert ev["verdict"] == "blocked"


def test_base_dir_confinement(tmp_path):
    inside = tmp_path / "inside"
    Recorder(dir=str(inside), agent="x").close()
    with pytest.raises(ValueError):
        Recorder(dir=str(tmp_path / "outside"), base_dir=str(inside))


def test_write_failure_never_crashes_the_agent(tmp_path):
    """CONTRIBUTING ground rule: a recorder must never crash the agent.
    When the run file becomes unwritable, recording stops with one warning
    and instrumented code keeps running."""
    rec = Recorder(dir=str(tmp_path), agent="bot")
    rec.log("before the break")
    rec._fp = _BrokenFP()

    with pytest.warns(RuntimeWarning, match="stopping recording"):
        rec.log("this write fails")
    # the agent-side call did NOT raise, and further recording is a no-op
    rec.log("silently dropped")
    rec.record_llm(request={"model": "m"}, response={"ok": True})
    rec.close()

    run = load_run(rec.path)
    assert [e["message"] for e in run.events if e["kind"] == "log"] == [
        "before the break"
    ]


def test_writing_after_close_is_a_noop(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.log("kept")
    rec.log("dropped: recorder already closed")
    assert len(load_run(rec.path).events) == 1

import asyncio

import pytest

from backspin import Recorder, load_run


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
    with pytest.raises(RuntimeError):
        with Recorder(dir=str(tmp_path), agent="bot") as rec:
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

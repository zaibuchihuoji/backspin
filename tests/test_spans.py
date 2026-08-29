"""Spans: nested, async-safe structure for recorded runs."""
import asyncio

import pytest

from backspin import Recorder, load_run


def test_nested_spans(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.log("top")
        with rec.span("agent-loop"):
            rec.log("inside loop")
            with rec.span("tool-call"):
                rec.record_tool(name="search", args={"q": "x"}, result="hit")
        rec.log("after")

    events = load_run(rec.path).events
    spans = [e for e in events if e["kind"] == "span"]
    assert len(spans) == 4  # 2 enter + 2 exit
    enters = [e for e in spans if e["phase"] == "enter"]
    assert [e["name"] for e in enters] == ["agent-loop", "tool-call"]
    assert enters[0]["depth"] == 0 and enters[0].get("parent") is None
    assert enters[1]["depth"] == 1 and enters[1]["parent"] == enters[0]["span_id"]
    # events inside a span carry its id and depth
    inside = [e for e in events if e.get("message") == "inside loop"][0]
    assert inside["span_id"] == enters[0]["span_id"] and inside["depth"] == 1
    tool = [e for e in events if e["kind"] == "tool"][0]
    assert tool["depth"] == 2 and tool["span_id"] == enters[1]["span_id"]
    # events after the span are back at depth 0
    after = [e for e in events if e.get("message") == "after"][0]
    assert "span_id" not in after and "depth" not in after
    # exit events carry duration
    exits = [e for e in spans if e["phase"] == "exit"]
    assert all(e["duration_ms"] >= 0 for e in exits)


def test_span_error_recorded_and_reraised(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with pytest.raises(ValueError):
        with rec:
            with rec.span("doomed"):
                raise ValueError("inside span")
    spans = [e for e in load_run(rec.path).events if e["kind"] == "span"]
    exits = [e for e in spans if e["phase"] == "exit"]
    assert len(exits) == 1
    assert exits[0]["error"] == "inside span"
    assert exits[0]["error_type"] == "ValueError"


def test_async_spans_are_isolated_per_task(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")

    async def branch(name: str):
        with rec.span(f"branch-{name}"):
            await asyncio.sleep(0.01)
            rec.log(f"inside {name}")

    with rec:
        async def main():
            await asyncio.gather(branch("a"), branch("b"))

        asyncio.run(main())

    logs = [e for e in load_run(rec.path).events if e["kind"] == "log"]
    by_name = {e["message"]: e for e in logs}
    enters = {
        e["name"]: e
        for e in load_run(rec.path).events
        if e["kind"] == "span" and e["phase"] == "enter"
    }
    # each task's log must belong to its OWN span, not interleaved
    assert by_name["inside a"]["span_id"] == enters["branch-a"]["span_id"]
    assert by_name["inside b"]["span_id"] == enters["branch-b"]["span_id"]
    assert by_name["inside a"]["span_id"] != by_name["inside b"]["span_id"]


def test_spans_do_not_inflate_duration_totals(tmp_path):
    import time

    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        with rec.span("outer"):
            time.sleep(0.02)
            rec.record_llm(
                request={"model": "m", "messages": [{"role": "user", "content": "x"}]},
                duration_ms=100.0,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
    t = load_run(rec.path).totals()
    # span duration excluded: only the LLM call's 100ms counts
    assert t["duration_ms"] == 100.0


def test_span_meta_recorded(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        with rec.span("tool", meta={"attempt": 2}):
            pass
    enter = [e for e in load_run(rec.path).events if e["kind"] == "span"][0]
    assert enter["meta"] == {"attempt": 2}

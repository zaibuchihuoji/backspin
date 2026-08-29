"""Edge cases: unicode, concurrency, lifecycle, garbage input."""
import asyncio
import json
import threading

import pytest

from backspin import Cassette, Recorder, ReplayMismatch, cli, load_run, stub_client
from backspin.fakes import message_data


def test_unicode_roundtrip(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="i18n")
    with rec:
        rec.log("中文日志 🎉")
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "巴黎天气怎么样?"}]},
            response=message_data("22°C ☀️ 晴"),
        )
    run = load_run(rec.path)
    assert run.events[0]["message"] == "中文日志 🎉"
    assert run.events[1]["request"]["messages"][0]["content"] == "巴黎天气怎么样?"
    assert run.events[1]["response"]["choices"][0]["message"]["content"] == "22°C ☀️ 晴"


def test_recorder_without_context_manager(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="x")
    rec.log("standalone")
    rec.close()
    assert load_run(rec.path).events[0]["message"] == "standalone"


def test_writes_after_close_are_dropped_silently(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="x")
    rec.close()
    rec.log("gone")  # must not raise
    assert load_run(rec.path).events == []


def test_circular_reference_does_not_crash(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="x")
    with rec:
        d: dict = {}
        d["self"] = d
        rec.record_tool(name="weird", args={"d": d})
    ev = load_run(rec.path).tool_calls()[0]
    # circular refs degrade to a repr instead of breaking the recording
    assert isinstance(ev["args"], str) and "self" in ev["args"]


def test_concurrent_recorders_are_isolated(tmp_path):
    def worker(i: int):
        r = Recorder(dir=str(tmp_path), agent=f"w{i}")
        for j in range(50):
            r.log(f"{i}-{j}")
        r.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    runs = [load_run(p) for p in sorted(glob_all(tmp_path))]
    assert len(runs) == 4
    for run in runs:
        assert len(run.events) == 50
        assert [e["seq"] for e in run.events] == list(range(1, 51))


def test_single_recorder_is_thread_safe(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="shared")

    def worker(k: int):
        for j in range(25):
            rec.log(f"{k}-{j}")

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rec.close()

    run = load_run(rec.path)
    seqs = sorted(e["seq"] for e in run.events)
    assert seqs == list(range(1, 101))
    assert len({e["message"] for e in run.events}) == 100  # no clobbered lines


def glob_all(tmp_path):
    import glob
    import os

    return glob.glob(os.path.join(str(tmp_path), "*.backspin.jsonl"))


def test_empty_cassette_raises(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="x")
    with rec:
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "x"}]},
            error=RuntimeError("no response ever"),
        )
    cassette = Cassette.from_run(load_run(rec.path))
    assert len(cassette) == 0
    stub = stub_client(cassette)
    with pytest.raises(ReplayMismatch):
        stub.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "x"}]
        )


def test_async_tool_error_recorded(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="x")
    with rec:

        @rec.tool
        async def boom():
            raise ValueError("a-boom")

        with pytest.raises(ValueError):
            asyncio.run(boom())

    ev = load_run(rec.path).tool_calls()[0]
    assert ev["error"] == "a-boom"


def test_cli_json_output(tmp_path, capsys):
    rec = Recorder(dir=str(tmp_path), agent="j")
    with rec:
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "q"}]},
            response=message_data("a"),
        )
    assert cli.main(["show", rec.path, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["agent"] == "j"
    assert len(data["events"]) == 1

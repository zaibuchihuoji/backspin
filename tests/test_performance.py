"""Rough performance guards: recording/loading must stay far from painful."""
import time

from backspin import Recorder, diff_runs, load_run
from backspin.fakes import message_data


def test_large_run_record_and_load(tmp_path):
    n = 20000
    rec = Recorder(dir=str(tmp_path), agent="perf")
    t0 = time.perf_counter()
    with rec:
        for i in range(n):
            rec.log(f"event {i} with some payload text to make it realistic")
    record_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    run = load_run(rec.path)
    load_s = time.perf_counter() - t0

    assert len(run.events) == n
    assert run.totals()["steps"] == n
    assert record_s < 60, f"recording {n} events took {record_s:.1f}s"
    assert load_s < 60, f"loading {n} events took {load_s:.1f}s"


def test_large_diff(tmp_path):
    def make(agent):
        rec = Recorder(dir=str(tmp_path), agent=agent)
        with rec:
            for i in range(4000):
                msgs = [{"role": "user", "content": f"prompt {i}"}]
                rec.record_llm(
                    request={"model": "m", "messages": msgs},
                    response=message_data("reply"),
                    duration_ms=1.0,
                    usage={"prompt_tokens": 1, "completion_tokens": 1},
                )
        return load_run(rec.path)

    a = make("a")
    b = make("b")
    t0 = time.perf_counter()
    rep = diff_runs(a, b)
    elapsed = time.perf_counter() - t0
    assert rep.identical
    assert elapsed < 60, f"diffing 2x4000 events took {elapsed:.1f}s"

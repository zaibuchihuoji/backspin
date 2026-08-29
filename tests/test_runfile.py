from backspin import Recorder, load_run
from backspin.runfile import FILE_SUFFIX


def test_header_first_and_sequence(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.log("one")
        rec.log("two")
    run = load_run(rec.path)
    assert run.agent == "bot"
    assert run.run_id
    assert run.path.endswith(FILE_SUFFIX)
    assert [e["seq"] for e in run.events] == [1, 2]
    assert run.by_kind("log")[0]["message"] == "one"


def test_totals(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "x"}]},
            usage={"prompt_tokens": 3, "completion_tokens": 4},
            duration_ms=10.0,
        )
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "y"}]},
            usage={"prompt_tokens": 1, "completion_tokens": 2},
            duration_ms=20.0,
        )
    t = load_run(rec.path).totals()
    assert t["llm_calls"] == 2
    assert t["prompt_tokens"] == 4 and t["completion_tokens"] == 6
    assert t["total_tokens"] == 10
    assert t["duration_ms"] == 30.0


def test_fingerprint_stable_and_sensitive():
    from backspin.runfile import fingerprint_request

    a = fingerprint_request("m", [{"role": "user", "content": "hi"}])
    b = fingerprint_request("m", [{"role": "user", "content": "hi"}])
    c = fingerprint_request("m", [{"role": "user", "content": "ho"}])
    d = fingerprint_request("other", [{"role": "user", "content": "hi"}])
    assert a == b and a != c and a != d


def test_load_run_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.backspin.jsonl"
    bad.write_text('{"kind": "notheader"}\n', encoding="utf-8")
    try:
        load_run(str(bad))
    except ValueError as exc:
        assert "header" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_jsonable_degrades_to_repr():
    from backspin.runfile import jsonable

    obj = object()
    assert jsonable(obj).startswith("<object object")
    assert jsonable({"ok": 1}) == {"ok": 1}

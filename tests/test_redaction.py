import json

from backspin import Recorder, load_run
from backspin.fakes import message_data
from backspin.redaction import mask, redact_strings
from backspin.runfile import fingerprint_request


def test_mask_strings_across_event_types(tmp_path):
    rec = Recorder(
        dir=str(tmp_path),
        agent="sec",
        redact=redact_strings(mask(r"sk-[A-Za-z0-9]{8,}")),
    )
    with rec:
        rec.log("the key is sk-abcdef123456 ok")
        rec.record_llm(
            request={
                "model": "m",
                "messages": [{"role": "user", "content": "my token sk-zzzz99998888 leaked"}],
            },
            response=message_data("clean reply"),
            usage={"prompt_tokens": 1, "completion_tokens": 2},
            duration_ms=1.0,
        )

    raw = open(rec.path, encoding="utf-8").read()
    assert "sk-abcdef123456" not in raw
    assert "sk-zzzz99998888" not in raw
    assert "[redacted]" in raw

    run = load_run(rec.path)
    assert run.events[0]["message"] == "the key is [redacted] ok"
    assert run.events[1]["response"]["choices"][0]["message"]["content"] == "clean reply"
    # numbers must survive the deep transform untouched
    assert run.events[1]["usage"]["prompt_tokens"] == 1


def test_fingerprint_computed_before_redaction(tmp_path):
    raw_messages = [{"role": "user", "content": "token sk-abcdefgh1234 here"}]
    rec = Recorder(
        dir=str(tmp_path),
        agent="sec",
        redact=redact_strings(mask(r"sk-[A-Za-z0-9]{8,}")),
    )
    with rec:
        rec.record_llm(
            request={"model": "m", "messages": raw_messages},
            response=message_data("ok"),
        )
    ev = load_run(rec.path).llm_calls()[0]
    # fingerprints stay matchable against raw requests, so replay works
    assert ev["fingerprint"] == fingerprint_request("m", raw_messages)
    # ...while the stored request is redacted
    assert "sk-abcdefgh1234" not in json.dumps(ev["request"])


def test_custom_redactor_and_default(tmp_path):
    # default: nothing is redacted
    rec = Recorder(dir=str(tmp_path), agent="plain")
    with rec:
        rec.log("keep my secret-value")
    assert "secret-value" in load_run(rec.path).events[0]["message"]

    # custom: anything the user wants
    rec2 = Recorder(
        dir=str(tmp_path),
        agent="custom",
        redact=lambda v: "<str>" if isinstance(v, str) else v,
    )
    with rec2:
        rec2.log("hello")
        rec2.record_tool(name="t", args={"n": 5}, result="text")
    events = load_run(rec2.path).events
    assert events[0]["message"] == "<str>"
    assert events[1]["args"]["n"] == 5  # non-strings untouched
    assert events[1]["result"] == "<str>"
    assert events[1]["name"] == "t"  # structural fields preserved

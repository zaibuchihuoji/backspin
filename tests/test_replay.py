import pytest

from backspin import (
    Cassette,
    Recorder,
    ReplayMismatch,
    ReplayMismatchWarning,
    diff_runs,
    load_run,
    stub_client,
)
from backspin.testing import FakeOpenAI

MSGS_A = [{"role": "user", "content": "a"}]
MSGS_B = [{"role": "user", "content": "b"}]


def build_run(dir_path) -> str:
    rec = Recorder(dir=str(dir_path), agent="bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(["first", "second"]))
        client.chat.completions.create(model="m", messages=MSGS_A)
        client.chat.completions.create(model="m", messages=MSGS_B)
    return rec.path


def test_cassette_from_run(tmp_path):
    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    assert len(cas) == 2


def test_stub_exact_match(tmp_path):
    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    stub = stub_client(cas)
    r = stub.chat.completions.create(model="m", messages=MSGS_A)
    assert r.choices[0].message.content == "first"
    r = stub.chat.completions.create(model="m", messages=MSGS_B)
    assert r.choices[0].message.content == "second"


def test_stub_order_fallback_warns(tmp_path):
    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    stub = stub_client(cas)
    with pytest.warns(ReplayMismatchWarning):
        r = stub.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "CHANGED"}]
        )
    assert r.choices[0].message.content == "first"
    assert stub.state.mismatches


def test_cassette_exhausted(tmp_path):
    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    stub = stub_client(cas)
    stub.chat.completions.create(model="m", messages=MSGS_A)
    stub.chat.completions.create(model="m", messages=MSGS_B)
    with pytest.raises(ReplayMismatch):
        stub.chat.completions.create(model="m", messages=MSGS_A)


def test_stream_replay(tmp_path):
    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    stub = stub_client(cas)
    chunks = list(
        stub.chat.completions.create(model="m", messages=MSGS_A, stream=True)
    )
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert "first" in text


def test_recorded_replay_is_identical(tmp_path):
    """The showcase loop: record -> replay through capture -> diff == clean."""
    path = build_run(tmp_path)
    run1 = load_run(path)
    cassette = Cassette.from_run(run1)

    rec2 = Recorder(dir=str(tmp_path), agent="bot", metadata={"replay_of": run1.run_id})
    with rec2:
        stub = rec2.capture_openai(stub_client(cassette))
        stub.chat.completions.create(model="m", messages=MSGS_A)
        stub.chat.completions.create(model="m", messages=MSGS_B)

    report = diff_runs(run1, load_run(rec2.path))
    assert report.identical


def test_patch_openai(tmp_path):
    pytest.importorskip("openai")
    import openai

    from backspin import patch_openai

    cas = Cassette.from_run(load_run(build_run(tmp_path)))
    saved = (openai.OpenAI, openai.AsyncOpenAI)
    try:
        with patch_openai(cas) as patched:
            client = openai.OpenAI()
            r = client.chat.completions.create(model="m", messages=MSGS_A)
            assert r.choices[0].message.content == "first"
            assert patched.sync is client
    finally:
        openai.OpenAI, openai.AsyncOpenAI = saved
    assert openai.OpenAI is saved[0]

import asyncio

import pytest

from backspin import Recorder, load_run
from backspin.testing import FakeAsyncOpenAI, FakeOpenAI


def test_sync_capture(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(["hello!", "done"]))
        r1 = client.chat.completions.create(
            model="m1", messages=[{"role": "user", "content": "hi"}]
        )
        client.chat.completions.create(
            model="m1", messages=[{"role": "user", "content": "hi again"}]
        )
        assert r1.choices[0].message.content == "hello!"

    llm = load_run(rec.path).llm_calls()
    assert len(llm) == 2
    assert llm[0]["request"]["messages"][0]["content"] == "hi"
    assert llm[0]["response"]["choices"][0]["message"]["content"] == "hello!"
    assert llm[0]["usage"]["prompt_tokens"] == 10
    assert llm[0]["duration_ms"] >= 0
    assert llm[0]["fingerprint"] != llm[1]["fingerprint"]


def test_streaming_capture_reconstructs(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(["streamed answer"]))
        chunks = list(
            client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "go"}], stream=True
            )
        )
        assert len(chunks) > 1  # passthrough preserved

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["reconstructed_from_stream"] is True
    assert ev["response"]["choices"][0]["message"]["content"] == "streamed answer"
    assert ev["usage"]["prompt_tokens"] == 10


def test_error_capture(tmp_path):
    from types import SimpleNamespace

    class Failing:
        def __init__(self):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kw):
            raise ValueError("api down")

    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        client = rec.capture_openai(Failing())
        with pytest.raises(ValueError):
            client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "x"}]
            )

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["error"] == "api down"
    assert ev["request"]["messages"][0]["content"] == "x"


def test_async_capture(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        client = rec.capture_openai(FakeAsyncOpenAI(["async hi"]))

        async def go():
            r = await client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "x"}]
            )
            return r.choices[0].message.content

        assert asyncio.run(go()) == "async hi"

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["choices"][0]["message"]["content"] == "async hi"


def test_unserializable_kwargs_dropped_not_fatal(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(["ok"]))
        client.chat.completions.create(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            extra_callable=lambda: None,
        )
    ev = load_run(rec.path).llm_calls()[0]
    assert "extra_callable" not in ev["request"]
    assert ev["request"]["model"] == "m"

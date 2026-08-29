"""Integration tests: the real openai SDK against a local mock server.

These exercise real HTTP, real SSE parsing and real SDK objects — no fakes
on the SDK side. The only thing mocked is the OpenAI API itself.
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("openai")

from openai import AsyncOpenAI, OpenAI  # noqa: E402

from backspin import Cassette, Recorder, load_run, stub_client  # noqa: E402

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "look up the weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]


def make_client(base_url: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key="sk-test", max_retries=0, timeout=15.0)


def test_real_sync_capture(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        resp = client.chat.completions.create(
            model="mock-gpt",
            messages=[{"role": "user", "content": "hello there"}],
        )

    # passthrough fidelity: a genuine SDK object came back
    assert resp.object == "chat.completion"
    assert resp.choices[0].message.content == "echo: hello there"

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["model"] == "mock-gpt"
    assert ev["request"]["messages"][0]["content"] == "hello there"
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: hello there"
    assert ev["usage"]["prompt_tokens"] == 12
    assert ev["usage"]["completion_tokens"] == 7
    assert ev["fingerprint"]


def test_real_streaming_capture(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        stream = client.chat.completions.create(
            model="mock-gpt",
            messages=[{"role": "user", "content": "hello stream"}],
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = list(stream)

    # real SDK chunk objects passed through untouched
    assert all(hasattr(c, "model_dump") for c in chunks)
    text = "".join(
        c.choices[0].delta.content or "" for c in chunks if c.choices
    )
    assert text == "echo: hello stream"

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["reconstructed_from_stream"] is True
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: hello stream"
    assert ev["usage"]["prompt_tokens"] == 12


def test_real_stream_context_manager(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        with client.chat.completions.create(
            model="mock-gpt",
            messages=[{"role": "user", "content": "ctx"}],
            stream=True,
        ) as stream:
            text = "".join(c.choices[0].delta.content or "" for c in stream if c.choices)

    assert text == "echo: ctx"
    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: ctx"


def test_real_tool_call_sync(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        resp = client.chat.completions.create(
            model="mock-gpt",
            messages=[{"role": "user", "content": "weather in town?"}],
            tools=TOOLS,
        )

    assert resp.choices[0].finish_reason == "tool_calls"
    tc = resp.choices[0].message.tool_calls[0]
    assert tc.function.name == "get_weather"
    assert json.loads(tc.function.arguments) == {"city": "Paris"}

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["request"]["tools"] == TOOLS
    msg = ev["response"]["choices"][0]["message"]
    assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"city": "Paris"}


def test_real_tool_call_streaming(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        stream = client.chat.completions.create(
            model="mock-gpt",
            messages=[{"role": "user", "content": "weather in town?"}],
            tools=TOOLS,
            stream=True,
            stream_options={"include_usage": True},
        )
        for _ in stream:
            pass

    msg = load_run(rec.path).llm_calls()[0]["response"]["choices"][0]["message"]
    assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
    # argument deltas must be concatenated in order
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"city": "Paris"}
    assert load_run(rec.path).llm_calls()[0]["response"]["choices"][0]["finish_reason"] == "tool_calls"


def test_real_async_capture(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")

    async def main():
        client = rec.capture_openai(
            AsyncOpenAI(base_url=openai_base_url, api_key="sk-test", max_retries=0)
        )
        try:
            stream = await client.chat.completions.create(
                model="mock-gpt",
                messages=[{"role": "user", "content": "async hello"}],
                stream=True,
                stream_options={"include_usage": True},
            )
            text = ""
            async for c in stream:
                if c.choices:
                    text += c.choices[0].delta.content or ""
            return text
        finally:
            await client.close()

    text = asyncio.run(main())
    assert text == "echo: async hello"

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: async hello"
    assert ev["usage"]["prompt_tokens"] == 12


def test_real_error_capture(tmp_path, openai_base_url):
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        with pytest.raises(Exception):
            client.chat.completions.create(
                model="mock-gpt",
                messages=[{"role": "user", "content": "boom please"}],
            )

    ev = load_run(rec.path).llm_calls()[0]
    assert "exploded" in ev["error"]
    assert ev["request"]["messages"][0]["content"] == "boom please"


def test_real_run_replays_offline(tmp_path, openai_base_url):
    """A run captured from the REAL SDK must replay through the stub."""
    rec = Recorder(dir=str(tmp_path), agent="it")
    with rec:
        client = rec.capture_openai(make_client(openai_base_url))
        live1 = client.chat.completions.create(
            model="mock-gpt", messages=[{"role": "user", "content": "one"}]
        )
        live2 = client.chat.completions.create(
            model="mock-gpt", messages=[{"role": "user", "content": "two"}]
        )

    run = load_run(rec.path)
    stub = stub_client(Cassette.from_run(run))
    r1 = stub.chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "one"}]
    )
    r2 = stub.chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "two"}]
    )
    assert r1.choices[0].message.content == live1.choices[0].message.content
    assert r2.choices[0].message.content == live2.choices[0].message.content

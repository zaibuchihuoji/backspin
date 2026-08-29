"""Anthropic integration tests: real SDK -> capture -> mock HTTP server."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("anthropic")

import anthropic

from backspin import Recorder, load_run
from backspin.cost import cost_report
from backspin.testing import FakeAnthropic


def make_client(origin: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=origin, api_key="sk-test", max_retries=0, timeout=15.0)


def test_anthropic_sync_capture(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")
    with rec:
        client = rec.capture_anthropic(make_client(anthropic_origin))
        msg = client.messages.create(
            model="claude-sonnet-4",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi there"}],
        )

    assert msg.content[0].text == "echo: hi there"  # real SDK object passthrough

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["provider"] == "anthropic"
    assert ev["model"] == "claude-sonnet-4"
    assert ev["request"]["messages"][0]["content"] == "hi there"
    assert ev["request"]["max_tokens"] == 100
    assert ev["response"]["content"][0]["text"] == "echo: hi there"
    # usage normalized for cost/diff interop
    assert ev["usage"]["prompt_tokens"] == 21
    assert ev["usage"]["completion_tokens"] == 13
    assert ev["fingerprint"]


def test_anthropic_streaming_capture(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")
    with rec:
        client = rec.capture_anthropic(make_client(anthropic_origin))
        stream = client.messages.create(
            model="claude-sonnet-4",
            max_tokens=100,
            messages=[{"role": "user", "content": "hello stream"}],
            stream=True,
        )
        events = list(stream)

    assert len(events) > 3  # raw events passed through untouched

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["reconstructed_from_stream"] is True
    text = "".join(
        b.get("text", "") for b in ev["response"]["content"] if b.get("type") == "text"
    )
    assert text == "echo: hello stream"
    assert ev["usage"]["prompt_tokens"] == 21
    assert ev["usage"]["completion_tokens"] == 13


def test_anthropic_tool_use_capture(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")
    tools = [{
        "name": "get_weather",
        "description": "weather lookup",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
    }]
    with rec:
        client = rec.capture_anthropic(make_client(anthropic_origin))
        msg = client.messages.create(
            model="claude-sonnet-4", max_tokens=100, tools=tools,
            messages=[{"role": "user", "content": "weather in town?"}],
        )

    tool_block = next(
        b for b in msg.content if getattr(b, "type", None) == "tool_use"
    )
    assert tool_block.name == "get_weather"
    assert tool_block.input == {"city": "Paris"}

    ev = load_run(rec.path).llm_calls()[0]
    assert ev["request"]["tools"] == tools
    blocks = ev["response"]["content"]
    tool_blocks = [b for b in blocks if b.get("type") == "tool_use"]
    assert tool_blocks and tool_blocks[0]["name"] == "get_weather"
    assert tool_blocks[0]["input"] == {"city": "Paris"}


def test_anthropic_async_capture(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")

    async def main():
        client = rec.capture_anthropic(
            anthropic.AsyncAnthropic(base_url=anthropic_origin, api_key="sk-test", max_retries=0)
        )
        try:
            return await client.messages.create(
                model="claude-sonnet-4", max_tokens=100,
                messages=[{"role": "user", "content": "async hi"}],
            )
        finally:
            await client.close()

    msg = asyncio.run(main())
    assert msg.content[0].text == "echo: async hi"
    ev = load_run(rec.path).llm_calls()[0]
    assert ev["response"]["content"][0]["text"] == "echo: async hi"


def test_anthropic_error_capture(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")
    with rec:
        client = rec.capture_anthropic(make_client(anthropic_origin))
        with pytest.raises(anthropic.APIStatusError):
            client.messages.create(
                model="claude-sonnet-4", max_tokens=10,
                messages=[{"role": "user", "content": "boom please"}],
            )

    ev = load_run(rec.path).llm_calls()[0]
    assert "exploded" in ev["error"]
    assert ev["request"]["messages"][0]["content"] == "boom please"


def test_anthropic_cost_computed(tmp_path, anthropic_origin):
    rec = Recorder(dir=str(tmp_path), agent="an")
    with rec:
        client = rec.capture_anthropic(make_client(anthropic_origin))
        client.messages.create(
            model="claude-sonnet-4", max_tokens=100,
            messages=[{"role": "user", "content": "cost check"}],
        )
    report = cost_report(load_run(rec.path))
    assert report["complete"] is True
    # 21 in @ $3/M + 13 out @ $15/M
    assert abs(report["total_usd"] - (21 / 1e6 * 3 + 13 / 1e6 * 15)) < 1e-9


def test_fake_anthropic_capture(tmp_path):

    rec = Recorder(dir=str(tmp_path), agent="fake")
    with rec:
        client = rec.capture_anthropic(FakeAnthropic(["scripted reply"]))
        msg = client.messages.create(
            model="m", max_tokens=10,
            messages=[{"role": "user", "content": "q"}],
        )
    assert msg.content[0].text == "scripted reply"
    ev = load_run(rec.path).llm_calls()[0]
    assert ev["provider"] == "anthropic"
    assert ev["response"]["content"][0]["text"] == "scripted reply"

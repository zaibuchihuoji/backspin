"""Proxy integration tests: real openai SDK -> proxy -> mock upstream."""
import pytest

pytest.importorskip("openai")

from openai import OpenAI  # noqa: E402

from backspin import Cassette, Recorder, load_run  # noqa: E402
from backspin.proxy import create_proxy_app  # noqa: E402
from tests.mock_openai_server import start_uvicorn  # noqa: E402


def make_proxy(tmp_path, upstream=None, cassette=None):
    app = create_proxy_app(
        upstream=upstream, cassette=cassette, runs_dir=str(tmp_path), agent="px"
    )
    origin = start_uvicorn(app)
    return origin + "/v1", app


def make_client(base_url: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key="sk-test", max_retries=0, timeout=15.0)


def test_proxy_record_sync(tmp_path, mock_openai_origin):
    base, app = make_proxy(tmp_path, upstream=mock_openai_origin)
    client = make_client(base)

    resp = client.chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "hello proxy"}]
    )
    assert resp.choices[0].message.content == "echo: hello proxy"

    run = load_run(app.state.recorder.path)
    ev = run.llm_calls()[0]
    assert ev["request"]["messages"][0]["content"] == "hello proxy"
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: hello proxy"
    assert ev["usage"]["prompt_tokens"] == 12
    assert ev["model"] == "mock-gpt"
    # the forwarded api key must never end up in the recording
    with open(app.state.recorder.path, encoding="utf-8") as f:
        assert "sk-test" not in f.read()


def test_proxy_record_streaming(tmp_path, mock_openai_origin):
    base, app = make_proxy(tmp_path, upstream=mock_openai_origin)
    client = make_client(base)

    stream = client.chat.completions.create(
        model="mock-gpt",
        messages=[{"role": "user", "content": "hello stream"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    chunks = list(stream)
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert text == "echo: hello stream"

    ev = load_run(app.state.recorder.path).llm_calls()[0]
    assert ev["response"]["reconstructed_from_stream"] is True
    assert ev["response"]["choices"][0]["message"]["content"] == "echo: hello stream"
    assert ev["usage"]["prompt_tokens"] == 12


def test_proxy_record_error(tmp_path, mock_openai_origin):
    base, app = make_proxy(tmp_path, upstream=mock_openai_origin)
    client = make_client(base)

    with pytest.raises(Exception):
        client.chat.completions.create(
            model="mock-gpt", messages=[{"role": "user", "content": "boom now"}]
        )

    ev = load_run(app.state.recorder.path).llm_calls()[0]
    assert "exploded" in ev["error"]
    assert ev["request"]["messages"][0]["content"] == "boom now"


def test_proxy_replay_no_upstream(tmp_path, mock_openai_origin):
    # 1. record a run through the proxy
    rec_base, rec_app = make_proxy(tmp_path, upstream=mock_openai_origin)
    live = make_client(rec_base).chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "replay me"}]
    )

    # 2. replay it from the cassette — no upstream at all
    cassette = Cassette.from_run(load_run(rec_app.state.recorder.path))
    replay_base, _ = make_proxy(tmp_path / "replay", cassette=cassette)
    replayed = make_client(replay_base).chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "replay me"}]
    )
    assert replayed.choices[0].message.content == live.choices[0].message.content

    # exhausted cassette -> 503 with a clear error
    with pytest.raises(Exception):
        make_client(replay_base).chat.completions.create(
            model="mock-gpt", messages=[{"role": "user", "content": "one too many"}]
        )


def test_proxy_replay_streaming(tmp_path, mock_openai_origin):
    rec_base, rec_app = make_proxy(tmp_path, upstream=mock_openai_origin)
    make_client(rec_base).chat.completions.create(
        model="mock-gpt", messages=[{"role": "user", "content": "stream replay"}]
    )
    cassette = Cassette.from_run(load_run(rec_app.state.recorder.path))
    replay_base, _ = make_proxy(tmp_path / "replay", cassette=cassette)

    stream = make_client(replay_base).chat.completions.create(
        model="mock-gpt",
        messages=[{"role": "user", "content": "stream replay"}],
        stream=True,
    )
    text = "".join(
        c.choices[0].delta.content or "" for c in stream if c.choices
    )
    assert text == "echo: stream replay"


def test_proxy_requires_exactly_one_mode(tmp_path):
    from backspin.proxy import create_proxy_app

    with pytest.raises(ValueError):
        create_proxy_app(runs_dir=str(tmp_path))
    with pytest.raises(ValueError):
        create_proxy_app(upstream="http://x", cassette=Cassette([]), runs_dir=str(tmp_path))


def test_proxy_anthropic_record_and_replay(tmp_path, anthropic_origin):
    """Anthropic /v1/messages protocol: record via proxy, replay via cassette."""
    anthropic = pytest.importorskip("anthropic")

    rec_base, rec_app = make_proxy(tmp_path, upstream=anthropic_origin)
    rec_origin = rec_base[: -len("/v1")]  # anthropic SDK appends /v1 itself
    live = anthropic.Anthropic(base_url=rec_origin, api_key="sk-test", max_retries=0)
    msg = live.messages.create(
        model="claude-sonnet-4", max_tokens=100,
        messages=[{"role": "user", "content": "anthropic proxy"}],
    )
    assert msg.content[0].text == "echo: anthropic proxy"

    run = load_run(rec_app.state.recorder.path)
    ev = run.llm_calls()[0]
    assert ev["provider"] == "anthropic"
    assert ev["response"]["content"][0]["text"] == "echo: anthropic proxy"
    assert ev["usage"]["prompt_tokens"] == 21

    # replay: same protocol served from the cassette, no upstream
    cassette = Cassette.from_run(run)
    replay_base, _ = make_proxy(tmp_path / "replay", cassette=cassette)
    replay_client = anthropic.Anthropic(
        base_url=replay_base[: -len("/v1")], api_key="sk-test", max_retries=0
    )
    replayed = replay_client.messages.create(
        model="claude-sonnet-4", max_tokens=100,
        messages=[{"role": "user", "content": "anthropic proxy"}],
    )
    assert replayed.content[0].text == "echo: anthropic proxy"
    assert replayed.usage.input_tokens == 21

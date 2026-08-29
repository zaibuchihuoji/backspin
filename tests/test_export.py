import json

import pytest

from backspin import Recorder, load_run
from backspin.export import export, export_pairs, export_sft
from backspin.testing import FakeOpenAI


def record_run(dir_path) -> str:
    rec = Recorder(dir=str(dir_path), agent="export-bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(["first answer", "final answer"]))
        client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "q1"}]
        )
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "q1"},
                      {"role": "assistant", "content": "first answer"},
                      {"role": "user", "content": "q2"}],
        )
    return rec.path


def test_export_pairs(tmp_path):
    run = load_run(record_run(tmp_path))
    rows = export_pairs(run)
    assert len(rows) == 2
    assert rows[0]["messages"][0]["content"] == "q1"
    assert rows[0]["response"] == "first answer"
    assert rows[0]["model"] == "gpt-4o-mini"
    assert rows[1]["response"] == "final answer"
    # every row is JSON-serializable on one line
    text = export(run, "pairs")
    assert len(text.splitlines()) == 2
    assert json.loads(text.splitlines()[1])["response"] == "final answer"


def test_export_sft(tmp_path):
    run = load_run(record_run(tmp_path))
    rows = export_sft(run)
    assert len(rows) == 1  # one chat sample per run
    messages = rows[0]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[-1] == {"role": "assistant", "content": "final answer"}


def test_export_unknown_format(tmp_path):
    run = load_run(record_run(tmp_path))
    with pytest.raises(ValueError):
        export(run, "weird")


def test_export_anthropic_shape(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="an")
    with rec:
        rec.record_llm(
            request={"model": "claude-sonnet-4",
                     "messages": [{"role": "user", "content": "hi"}]},
            response={"content": [{"type": "text", "text": "he"},
                                  {"type": "text", "text": "llo"}],
                      "usage": {"input_tokens": 1, "output_tokens": 1}},
            provider="anthropic",
        )
    rows = export_pairs(load_run(rec.path))
    assert rows[0]["response"] == "hello"
    assert rows[0]["model"] == "claude-sonnet-4"

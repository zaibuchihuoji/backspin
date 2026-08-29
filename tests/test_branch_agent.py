"""Agent-level what-if: re-run the actual agent against a mutated cassette."""
import pytest

from backspin import Recorder, branch_agent, diff_runs, load_run
from backspin.testing import FakeOpenAI

SCRIPT = [
    "Let me check the weather.",
    "It is 22C and sunny in Paris.",
    "Based on that: take sunglasses.",
]
MSGS = [{"role": "user", "content": "weather in Paris?"}]


def run_agent(client, rec):
    """A 3-call agent where each request depends on the previous answer."""
    rec.log("start")
    r1 = client.chat.completions.create(model="m", messages=MSGS)
    rec.log("r1: " + r1.choices[0].message.content)
    r2 = client.chat.completions.create(
        model="m", messages=MSGS + [{"role": "assistant", "content": r1.choices[0].message.content}]
    )
    rec.log("r2: " + r2.choices[0].message.content)
    r3 = client.chat.completions.create(
        model="m",
        messages=MSGS + [
            {"role": "assistant", "content": r2.choices[0].message.content},
            {"role": "user", "content": "summarize"},
        ],
    )
    return r3.choices[0].message.content


def record_original(tmp_path) -> str:
    rec = Recorder(dir=str(tmp_path), agent="agent-level")
    with rec:
        result = run_agent(rec.capture_openai(FakeOpenAI(SCRIPT)), rec)
    assert result == SCRIPT[2]
    return rec.path


def test_branch_agent_preserves_full_shape(tmp_path):
    original_path = record_original(tmp_path)
    branch_path = branch_agent(
        run_agent, original_path, {1: {"content": "It is raining."}}, dir=str(tmp_path)
    )
    branched = load_run(branch_path)
    original = load_run(original_path)

    # same shape: logs, tools, spans and llm calls all present
    assert [e["kind"] for e in original.events] == [e["kind"] for e in branched.events]
    assert branched.metadata["branch_of"] == original.run_id
    assert branched.metadata["branch_level"] == "agent"

    # the mutated answer is what the agent saw at step 1
    mutated_llm = branched.llm_calls()[1]
    assert mutated_llm["response"]["choices"][0]["message"]["content"] == "It is raining."
    # ...and it propagated into the agent's own log lines
    logs = [e["message"] for e in branched.events if e["kind"] == "log"]
    assert "r1: Let me check the weather." in logs
    assert "r2: It is raining." in logs


def test_branch_agent_diff_pins_first_divergence(tmp_path):
    original_path = record_original(tmp_path)
    branch_path = branch_agent(
        run_agent, original_path, {1: {"content": "It is raining."}}, dir=str(tmp_path)
    )
    report = diff_runs(load_run(original_path), load_run(branch_path))
    assert report.identical is False
    # events: 0=log, 1=llm#0, 2=log(r1), 3=llm#1(request embeds r1's UNCHANGED
    # answer), 4=log(r2 -- now carries the mutated answer) -> divergence at 4
    assert report.first_divergence == 4


def test_branch_agent_validation(tmp_path):
    original_path = record_original(tmp_path)
    with pytest.raises(TypeError):
        branch_agent("not-callable", original_path, {0: {"content": "x"}}, dir=str(tmp_path))
    with pytest.raises(ValueError):
        branch_agent(run_agent, original_path, {}, dir=str(tmp_path))

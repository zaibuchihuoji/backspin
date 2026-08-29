import json

import pytest

from backspin import Cassette, Recorder, branch, diff_runs, load_run, stub_client
from backspin.fakes import message_data
from backspin.testing import FakeOpenAI

REPLY_1 = "Paris it is."
REPLY_2 = "Final answer: 22C."
MSGS_A = [{"role": "user", "content": "weather?"}]


def record_original(dir_path) -> str:
    rec = Recorder(dir=str(dir_path), agent="bot")
    with rec:
        rec.log("start")
        client = rec.capture_openai(FakeOpenAI([REPLY_1, REPLY_2]))
        r1 = client.chat.completions.create(model="m", messages=MSGS_A)
        client.chat.completions.create(
            model="m",
            messages=[
                *MSGS_A,
                {"role": "assistant", "content": r1.choices[0].message.content},
            ],
        )
    return rec.path


def test_mutate_returns_new_cassette_original_untouched(tmp_path):
    cassette = Cassette.from_run(load_run(record_original(tmp_path)))
    mutated = cassette.mutate(0, content="Rome it is.")
    assert mutated is not cassette
    assert mutated.entries[0]["response"]["choices"][0]["message"]["content"] == "Rome it is."
    assert cassette.entries[0]["response"]["choices"][0]["message"]["content"] == REPLY_1


def test_mutate_tool_arguments(tmp_path):
    rec = Recorder(dir=str(tmp_path), agent="bot")
    with rec:
        rec.record_llm(
            request={"model": "m", "messages": MSGS_A},
            response=message_data(None, tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }]),
        )
    mutated = Cassette.from_run(load_run(rec.path)).mutate(
        0, tool_arguments={"city": "Rome"}
    )
    entry = mutated.entries[0]["response"]["choices"][0]["message"]
    args = entry["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args) == {"city": "Rome"}


def test_mutate_out_of_range_and_no_tool_calls(tmp_path):
    cassette = Cassette.from_run(load_run(record_original(tmp_path)))
    with pytest.raises(IndexError):
        cassette.mutate(99, content="x")
    with pytest.raises(ValueError):
        cassette.mutate(0, tool_arguments={"a": 1})  # plain text response


def test_stub_uses_mutated_answer(tmp_path):
    cassette = Cassette.from_run(load_run(record_original(tmp_path))).mutate(
        0, content="Rome it is."
    )
    stub = stub_client(cassette)
    r = stub.chat.completions.create(model="m", messages=MSGS_A)
    assert r.choices[0].message.content == "Rome it is."


def test_branch_records_mutated_replay(tmp_path):
    original_path = record_original(tmp_path)
    original = load_run(original_path)

    branch_path = branch(
        original_path, {0: {"content": "Rome it is."}}, dir=str(tmp_path)
    )
    branched = load_run(branch_path)
    assert branched.metadata["branch_of"] == original.run_id
    assert branched.metadata["mutations"] == {"0": {"content": "Rome it is."}}

    llm = branched.llm_calls()
    assert len(llm) == 2
    # call #0 answers with the mutation; call #1's REQUEST carries it forward
    assert llm[0]["response"]["choices"][0]["message"]["content"] == "Rome it is."
    second_request_messages = llm[1]["request"]["messages"]
    assert second_request_messages[-1]["content"] == "Rome it is."

    # the original file is untouched
    original_reply = load_run(original_path).llm_calls()[0]["response"]["choices"][0]
    assert original_reply["message"]["content"] == REPLY_1


def test_branch_diff_llm_only_finds_divergence(tmp_path):
    original_path = record_original(tmp_path)
    branch_path = branch(original_path, {0: {"content": "Rome it is."}}, dir=str(tmp_path))
    report = diff_runs(load_run(original_path), load_run(branch_path), llm_only=True)
    assert report.identical is False
    # call #0 itself matches (same request, mutation applies to response only);
    # call #1's request now embeds the mutated answer -> fingerprints diverge
    assert report.first_divergence == 1


def test_branch_requires_mutations(tmp_path):
    with pytest.raises(ValueError):
        branch(record_original(tmp_path), {}, dir=str(tmp_path))

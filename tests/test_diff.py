from backspin import Recorder, diff_runs, load_run
from backspin.fakes import message_data


def make_run(dir_path, prompts) -> str:
    rec = Recorder(dir=str(dir_path), agent="bot")
    with rec:
        rec.log("start")
        for i, content in enumerate(prompts):
            rec.record_llm(
                request={"model": "m", "messages": [{"role": "user", "content": content}]},
                response=message_data(f"reply-{i}"),
                duration_ms=10.0 * (i + 1),
                usage={"prompt_tokens": i + 1, "completion_tokens": 2},
            )
    return rec.path


def test_identical_runs(tmp_path):
    a = load_run(make_run(tmp_path, ["x", "y"]))
    b = load_run(make_run(tmp_path, ["x", "y"]))
    rep = diff_runs(a, b)
    assert rep.identical
    assert rep.first_divergence is None


def test_divergence_found(tmp_path):
    a = load_run(make_run(tmp_path, ["x", "y", "z"]))
    b = load_run(make_run(tmp_path, ["x", "CHANGED", "z"]))
    rep = diff_runs(a, b)
    # events: [log "start", llm x, llm y|CHANGED, llm z] -> diverge at index 2
    assert rep.first_divergence == 2
    assert not rep.identical
    step = rep.steps[0]
    assert step.same is True  # the log step still matches


def test_different_shape(tmp_path):
    a = load_run(make_run(tmp_path, ["x"]))
    b = load_run(make_run(tmp_path, ["x", "y"]))
    rep = diff_runs(a, b)
    assert not rep.identical
    assert rep.first_divergence is None  # requests match; shape differs
    assert rep.steps[1].same is True  # llm x matches
    assert rep.steps[2].same is None  # step exists on one side only


def test_metrics_in_totals(tmp_path):
    a = load_run(make_run(tmp_path, ["x"]))
    b = load_run(make_run(tmp_path, ["x"]))
    rep = diff_runs(a, b)
    assert rep.totals_a["prompt_tokens"] == 1
    assert rep.totals_b["completion_tokens"] == 2
    assert rep.to_dict()["identical"] is True

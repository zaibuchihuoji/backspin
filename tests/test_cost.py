from backspin import Recorder, load_run
from backspin.cost import cost_report, estimate_cost, lookup_price
from backspin.fakes import message_data


def test_exact_and_prefix_matching():
    assert lookup_price("gpt-4o") == (2.50, 10.00)
    assert lookup_price("gpt-4o-2024-11-20") == (2.50, 10.00)  # dated snapshot
    assert lookup_price("gpt-4o-mini") == (0.15, 0.60)  # longer prefix wins
    assert lookup_price("anthropic/claude-sonnet-4") == (3.00, 15.00)
    assert lookup_price("totally-unknown-model") is None
    assert lookup_price(None) is None


def test_estimate_cost_math():
    # gpt-4o-mini: $0.15/1M in, $0.60/1M out
    cost = estimate_cost("gpt-4o-mini", 1_000_000, 500_000)
    assert abs(cost - (0.15 + 0.30)) < 1e-9
    assert estimate_cost("unknown", 100, 100) is None
    assert estimate_cost("gpt-4o", 0, 0) is None


def make_run(dir_path, models):
    rec = Recorder(dir=str(dir_path), agent="cost")
    with rec:
        for model in models:
            rec.record_llm(
                request={"model": model, "messages": [{"role": "user", "content": "x"}]},
                response=message_data("r"),
                usage={"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
                duration_ms=1.0,
            )
    return rec.path


def test_run_cost_report(tmp_path):
    run = load_run(make_run(tmp_path, ["gpt-4o-mini", "gpt-4o"]))
    report = cost_report(run)
    assert abs(report["total_usd"] - (0.15 + 0.30 + 2.50 + 5.00)) < 1e-6
    assert report["complete"] is True


def test_run_cost_partial(tmp_path):
    run = load_run(make_run(tmp_path, ["gpt-4o", "mystery-model"]))
    report = cost_report(run)
    assert report["complete"] is False
    assert report["unknown_models"] == ["mystery-model"]
    assert abs(report["total_usd"] - 7.50) < 1e-6  # only the known call counted


def test_totals_include_cost(tmp_path):
    run = load_run(make_run(tmp_path, ["gpt-4o-mini"]))
    t = run.totals()
    assert abs(t["cost_usd"] - (0.15 + 0.30)) < 1e-6
    assert t["cost_complete"] is True

import json

from backspin import Recorder, load_run
from backspin.tui import (
    collect_runs,
    render_run_table,
    render_step,
    render_timeline,
    run_tui,
)


def make_runs(tmp_path, count=2):
    paths = []
    for i in range(count):
        rec = Recorder(dir=str(tmp_path), agent=f"tui-bot-{i}")
        with rec:
            rec.log("begin")
            rec.record_llm(
                request={"model": "m", "messages": [{"role": "user", "content": f"q{i}"}]},
                response={"choices": [{"message": {"role": "assistant", "content": "a"}}]},
                duration_ms=12.0,
                usage={"prompt_tokens": 3, "completion_tokens": 4},
            )
        paths.append(rec.path)
    return paths


def test_render_run_table(tmp_path):
    make_runs(tmp_path)
    table = render_run_table(collect_runs(str(tmp_path)))
    # newest run sorts first
    assert "tui-bot-0" in table and "tui-bot-1" in table
    assert "[1]" in table and "[2]" in table
    assert "q quit" in table


def test_render_timeline_and_step(tmp_path):
    make_runs(tmp_path, count=1)
    run = collect_runs(str(tmp_path))[0]
    timeline = render_timeline(run)
    assert "llm   m" in timeline
    assert "log   begin" in timeline

    step = render_step(run.events[0])
    assert json.loads(step)["message"] == "begin"


def test_interactive_walkthrough(tmp_path, capsys):
    make_runs(tmp_path)
    inputs = iter(["1", "2", "b", "q"])

    def fake_input():
        return next(inputs)

    seen = []
    run_tui(str(tmp_path), inp=fake_input, out=seen.append)
    output = "\n".join(seen)
    assert "tui-bot-0" in output
    assert "begin" in output          # timeline rendered
    assert '"model": "m"' in output   # step detail JSON shown

from backspin import Recorder, cli, load_run
from backspin.fakes import message_data


def make_run(dir_path, prompts) -> str:
    rec = Recorder(dir=str(dir_path), agent="cli-bot")
    with rec:
        rec.log("start")
        for i, content in enumerate(prompts):
            rec.record_llm(
                request={"model": "m", "messages": [{"role": "user", "content": content}]},
                response=message_data(f"reply-{i}"),
                duration_ms=10.0,
                usage={"prompt_tokens": 1, "completion_tokens": 2},
            )
    return rec.path


def test_ls(tmp_path, capsys):
    make_run(tmp_path, ["x"])
    rc = cli.main(["ls", str(tmp_path)])
    assert rc == 0
    assert "cli-bot" in capsys.readouterr().out


def test_ls_empty_dir(tmp_path, capsys):
    assert cli.main(["ls", str(tmp_path)]) == 1


def test_show_and_step(tmp_path, capsys):
    path = make_run(tmp_path, ["x", "y"])
    assert cli.main(["show", path]) == 0
    assert "llm" in capsys.readouterr().out

    assert cli.main(["show", path, "--step", "2"]) == 0
    import json

    ev = json.loads(capsys.readouterr().out)
    assert ev["seq"] == 2 and ev["kind"] == "llm"


def test_diff_exit_codes(tmp_path, capsys):
    a = make_run(tmp_path, ["x", "y"])
    b = make_run(tmp_path, ["x", "y"])
    assert cli.main(["diff", a, b]) == 0

    c = make_run(tmp_path, ["x", "DIFFERENT"])
    assert cli.main(["diff", a, c]) == 1
    assert "diverge" in capsys.readouterr().out.lower()


def test_show_missing_file_fails(tmp_path, capsys):
    assert cli.main(["show", str(tmp_path / "nope.backspin.jsonl")]) == 2
    assert "error" in capsys.readouterr().err.lower()

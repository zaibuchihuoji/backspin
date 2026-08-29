import json

import pytest

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


def test_branch(tmp_path, capsys):
    path = make_run(tmp_path, ["x", "y"])
    out_dir = tmp_path / "branches"
    rc = cli.main(
        ["branch", path, "--step", "0", "--content", "WHAT IF", "--dir", str(out_dir)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "branch run:" in out

    branch_path = next(
        line.split(":", 1)[1].strip()
        for line in out.splitlines() if line.startswith("branch run:")
    )
    run = load_run(branch_path)
    assert run.metadata["branch_of"] is not None
    assert run.llm_calls()[0]["response"]["choices"][0]["message"]["content"] == "WHAT IF"


def test_branch_requires_a_mutation(tmp_path, capsys):
    path = make_run(tmp_path, ["x"])
    assert cli.main(["branch", path, "--step", "0"]) == 2
    assert "nothing to mutate" in capsys.readouterr().out


def test_export_pairs_and_sft(tmp_path, capsys):
    path = make_run(tmp_path, ["q1", "q2"])

    assert cli.main(["export", path, "--format", "pairs"]) == 0
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 2

    out_file = tmp_path / "sft.jsonl"
    assert cli.main(["export", path, "--format", "sft", "-o", str(out_file)]) == 0
    assert out_file.exists() and out_file.stat().st_size > 0


def test_share_writes_single_file_html(tmp_path, capsys):
    pytest.importorskip("fastapi")  # share inlines the FastAPI-served viewer assets
    path = make_run(tmp_path, ["x"])
    out_file = tmp_path / "shared.html"
    assert cli.main(["share", path, "-o", str(out_file)]) == 0
    html = out_file.read_text(encoding="utf-8")
    assert "backspin" in html
    assert "__BACKSPIN_EMBED__" in html  # the run data is inlined
    assert "sk-test" not in html  # sanity: nothing unexpected injected

from pathlib import Path

from backspin import Recorder
from backspin.share import build_share_html, write_share_html


def record_run(dir_path) -> str:
    rec = Recorder(dir=str(dir_path), agent="share-bot", metadata={"team": "core"})
    with rec:
        rec.log("hey <script>alert(1)</script>")
        rec.record_llm(
            request={"model": "m", "messages": [{"role": "user", "content": "q"}]},
            response={"choices": [{"message": {"role": "assistant", "content": "a"}}]},
            duration_ms=5.0,
            usage={"prompt_tokens": 1, "completion_tokens": 2},
        )
    return rec.path


def test_share_html_is_self_contained(tmp_path):
    out = Path(write_share_html(record_run(tmp_path)))
    html = out.read_text(encoding="utf-8")

    # viewer assets are inlined, nothing is fetched
    assert 'href="style.css"' not in html
    assert 'src="app.js"' not in html
    assert "renderWaterfall" in html  # app.js content present
    assert ".row" in html             # style.css content present
    # run data embedded for the viewer
    assert "__BACKSPIN_EMBED__" in html
    assert "share-bot" in html
    # output lands next to the run file with a .share.html suffix
    assert out.name.endswith(".share.html")


def test_share_html_escapes_script_injection(tmp_path):
    html = build_share_html(record_run(tmp_path))
    assert "<script>alert(1)</script>" not in html.split("__BACKSPIN_EMBED__")[1]
    assert "<\\/script>" in html.split("__BACKSPIN_EMBED__")[1]


def test_custom_output_path(tmp_path):
    out = tmp_path / "custom" / "named.html"
    out.parent.mkdir()
    result = write_share_html(record_run(tmp_path), str(out))
    assert Path(result).read_text(encoding="utf-8").startswith("<!doctype html>")

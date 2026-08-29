"""Single-file HTML sharing: one run + the whole viewer in one .html file.

``build_share_html`` inlines the viewer's CSS/JS and the run's data, so a
teammate can open the file in any browser and step through the run — no
server, no install, no data leaves the file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .runfile import load_run

_UI_DIR = Path(__file__).resolve().parent / "ui"


def _safe_json(obj: Any) -> str:
    """JSON that is safe to embed inside a <script> block."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_share_html(run_path: str, title: Optional[str] = None) -> str:
    run = load_run(run_path)
    data = run.summary()
    data["events"] = run.events

    html = (_UI_DIR / "index.html").read_text(encoding="utf-8")
    css = (_UI_DIR / "style.css").read_text(encoding="utf-8")
    js = (_UI_DIR / "app.js").read_text(encoding="utf-8")

    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        "<style>\n" + css + "\n</style>",
    )
    embed = (
        "<script>window.__BACKSPIN_EMBED__ = " + _safe_json(data) + ";</script>\n"
        "<script>\n" + js + "\n</script>"
    )
    html = html.replace('<script src="app.js"></script>', embed)
    if title:
        html = html.replace("<title>backspin — agent run viewer</title>",
                            "<title>" + title + "</title>")
    return html


def write_share_html(run_path: str, out_path: Optional[str] = None) -> str:
    """Build the share file; returns the written path."""
    run = load_run(run_path)
    if out_path is None:
        out_path = str(Path(run_path).with_suffix(".share.html"))
    html = build_share_html(run_path, title=f"backspin — {run.agent}")
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path

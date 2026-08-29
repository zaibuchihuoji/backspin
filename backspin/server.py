"""Local viewer: a small FastAPI app that serves the timeline UI.

Read-only over the runs directory: the API only ever exposes files that
are plain names directly inside the resolved runs dir, and never serves
anything outside it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from .diff import diff_runs
from .runfile import FILE_SUFFIX, load_run

UI_DIR = Path(__file__).resolve().parent / "ui"


def _resolve_runs_dir(runs_dir: str) -> Path:
    root = Path(os.path.realpath(os.path.expanduser(runs_dir)))
    if not root.is_dir():
        raise NotADirectoryError(f"runs directory not found: {runs_dir}")
    return root


def _safe_run_path(root: Path, name: str) -> Path:
    """Only bare file names directly inside ``root`` are ever readable."""
    if (
        not name.endswith(FILE_SUFFIX)
        or "/" in name
        or "\\" in name
        or name in (".", "..")
    ):
        raise HTTPException(status_code=404, detail="no such run")
    path = Path(os.path.realpath(root / name))
    if os.path.dirname(str(path)) != str(root):
        raise HTTPException(status_code=404, detail="no such run")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such run")
    return path


def create_app(runs_dir: str = "runs") -> FastAPI:
    app = FastAPI(title="backspin viewer", docs_url=None, redoc_url=None)
    root = _resolve_runs_dir(runs_dir)

    @app.get("/api/runs")
    def list_runs() -> List[Dict[str, Any]]:
        runs = []
        for name in sorted(os.listdir(root), reverse=True):
            if not name.endswith(FILE_SUFFIX):
                continue
            try:
                runs.append(load_run(str(root / name)).summary())
            except ValueError:
                runs.append({"name": name, "agent": "?", "invalid": True})
        return runs

    @app.get("/api/run/{name}")
    def get_run(name: str) -> Dict[str, Any]:
        path = _safe_run_path(root, name)
        try:
            run = load_run(str(path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data = run.summary()
        data["events"] = run.events
        return data

    @app.get("/api/diff")
    def diff(a: str, b: str) -> Dict[str, Any]:
        run_a = load_run(str(_safe_run_path(root, a)))
        run_b = load_run(str(_safe_run_path(root, b)))
        return diff_runs(run_a, run_b).to_dict()

    @app.exception_handler(NotADirectoryError)
    def bad_dir(_req, exc: NotADirectoryError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
    return app


def serve(runs_dir: str = "runs", host: str = "127.0.0.1", port: int = 8787) -> None:
    import uvicorn

    uvicorn.run(create_app(runs_dir), host=host, port=port, log_level="warning")

"""Keyboard-driven run viewer for the terminal.

``backspin tui`` walks through runs with numbered menus — no mouse, no
browser, works over ssh. The interactive loop is intentionally simple
(input + print); the rendering functions are pure and unit-tested.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from .runfile import FILE_SUFFIX, Run, load_run


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def collect_runs(dir_path: str) -> List[Run]:
    import glob
    import os

    runs = []
    for path in sorted(glob.glob(os.path.join(dir_path, f"*{FILE_SUFFIX}")), reverse=True):
        try:
            runs.append(load_run(path))
        except ValueError:
            continue
    return runs


def render_run_table(runs: List[Run]) -> str:
    lines = []
    if not runs:
        lines.append("(no recordings found)")
    for i, run in enumerate(runs, 1):
        t = run.totals()
        lines.append(
            f" [{i}] {run.agent:<14} steps={t['steps']:<5} "
            f"llm={t['llm_calls']:<4} tokens={t['total_tokens']:<7} "
            f"~${t['cost_usd']:.4f}"
        )
    lines.append("")
    lines.append("type a number to open a run  |  r refresh  |  q quit")
    return "\n".join(lines)


def _step_line(ev: Dict[str, Any]) -> str:
    seq = ev.get("seq", 0)
    dur = _fmt_ms(ev.get("duration_ms") or 0)
    kind = ev.get("kind", "?")
    indent = "    " * (ev.get("depth") or 0)
    if kind == "llm":
        usage = ev.get("usage") or {}
        tok = f"tok {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)}"
        err = "  ERR " + str(ev["error"]) if ev.get("error") else ""
        return f"{indent}#{seq:<3} llm   {ev.get('model') or '?'!s:<20} {dur:>8}  {tok}{err}"
    if kind == "tool":
        err = "  ERR " + str(ev["error"]) if ev.get("error") else ""
        return f"{indent}#{seq:<3} tool  {ev.get('name') or '?'!s:<20} {dur:>8}{err}"
    if kind == "span":
        phase = "enter" if ev.get("phase") == "enter" else "exit"
        err = "  ERR " + str(ev["error"]) if ev.get("error") else ""
        return f"{indent}#{seq:<3} span  [{phase}] {ev.get('name', '')}  {dur:>8}{err}"
    if kind == "log":
        return f"{indent}#{seq:<3} log   {ev.get('message', '')}"
    if kind == "error":
        return f"{indent}#{seq:<3} ERROR {ev.get('error_type', '')}: {ev.get('message', '')}"
    return f"{indent}#{seq:<3} {kind}"


def render_timeline(run: Run) -> str:
    meta = run.metadata
    extra = ", ".join(f"{k}={v}" for k, v in meta.items() if k in ("replay_of", "branch_of"))
    lines = [f"run {run.run_id}  agent={run.agent}" + (f"  ({extra})" if extra else "")]
    for ev in run.events:
        lines.append(_step_line(ev))
    lines.append("")
    lines.append("type a step number for details  |  b back  |  q quit")
    return "\n".join(lines)


def render_step(ev: Dict[str, Any], max_lines: int = 40) -> str:
    body = json.dumps(ev, ensure_ascii=False, indent=2, default=str)
    lines = body.splitlines()
    if len(lines) > max_lines:
        note = f"... ({len(lines) - max_lines} more lines, see the file)"
        lines = [*lines[:max_lines], note]
    return "\n".join(lines)


def run_tui(
    dir_path: str = "runs",
    *,
    inp: Optional[Callable[[], str]] = None,
    out: Optional[Callable[[str], None]] = None,
) -> None:
    """Interactive loop. ``inp``/``out`` are injectable for tests."""
    read = inp or input
    write = out or print

    write(f"backspin tui — runs in {dir_path!r}")
    while True:
        runs = collect_runs(dir_path)
        write(render_run_table(runs))
        choice = read().strip().lower()
        if choice == "q":
            return
        if choice == "r" or choice == "":
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(runs):
            run = runs[int(choice) - 1]
            write(render_timeline(run))
            while True:
                sub = read().strip().lower()
                if sub == "q":
                    return
                if sub == "b":
                    break
                if sub.isdigit():
                    for ev in run.events:
                        if str(ev.get("seq")) == sub:
                            write(render_step(ev))
                            break
                    else:
                        write(f"no step #{sub}")
                        continue
                    write("b back  |  another step number  |  q quit")
                else:
                    write("b back  |  q quit")

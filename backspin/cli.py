"""The ``backspin`` command line: ls, show, diff, ui."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .diff import DiffReport, diff_runs
from .runfile import FILE_SUFFIX, Run, load_run


# --- tiny ANSI helpers (ASCII output only, Windows-console safe) ----------


class C:
    """ANSI helpers: c.red("text") when colors are on, plain text otherwise."""

    def __init__(self, enabled: bool):
        self.on = enabled

    @property
    def reset(self) -> str:
        return "\033[0m" if self.on else ""

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else str(s)

    def dim(self, s):
        return self._w("2", s)

    def bold(self, s):
        return self._w("1", s)

    def red(self, s):
        return self._w("31", s)

    def green(self, s):
        return self._w("32", s)

    def yellow(self, s):
        return self._w("33", s)

    def blue(self, s):
        return self._w("36", s)


def _color() -> C:
    return C(sys.stdout.isatty())


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    return f"{ms:.0f}ms"


def _find_runs(dir_path: str) -> List[str]:
    pattern = os.path.join(dir_path, f"*{FILE_SUFFIX}")
    return sorted(glob.glob(pattern), reverse=True)


# --- subcommands -----------------------------------------------------------


def cmd_ls(args: argparse.Namespace) -> int:
    c = _color()
    files = _find_runs(args.dir)
    if not files:
        print(c.dim(f"no {FILE_SUFFIX} files under {args.dir!r}") + c.reset)
        return 1
    header = f"{'run':<44} {'agent':<14} {'steps':>5} {'llm':>4} {'tool':>4} {'tokens':>7}"
    print(c.bold(header) + c.reset)
    for path in files:
        try:
            run = load_run(path)
        except ValueError as exc:
            print(f"{os.path.basename(path):<44} {c.red('invalid: ' + str(exc))}{c.reset}")
            continue
        t = run.totals()
        print(
            f"{os.path.basename(path):<44} {run.agent:<14} {t['steps']:>5} "
            f"{t['llm_calls']:>4} {t['tool_calls']:>4} {t['total_tokens']:>7}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    c = _color()
    run = load_run(args.file)
    if args.json:
        print(json.dumps(run.summary() | {"events": run.events}, ensure_ascii=False, indent=2))
        return 0
    if args.step is not None:
        for ev in run.events:
            if ev.get("seq") == args.step:
                print(json.dumps(ev, ensure_ascii=False, indent=2, default=str))
                return 0
        print(c.red(f"no step #{args.step} in {args.file}") + c.reset)
        return 1

    t = run.totals()
    meta = run.metadata
    replay_of = f"  (replay of {meta['replay_of']})" if "replay_of" in meta else ""
    print(c.bold(f"run {run.run_id}") + f"  agent={run.agent}{replay_of}")
    print(
        c.dim(
            f"steps={t['steps']} llm={t['llm_calls']} tool={t['tool_calls']} "
            f"tokens={t['prompt_tokens']}+{t['completion_tokens']} "
            f"duration={_fmt_ms(t['duration_ms'])}"
        )
        + c.reset
    )
    print()
    for ev in run.events:
        kind = ev.get("kind", "?")
        seq = ev.get("seq", 0)
        dur = _fmt_ms(ev.get("duration_ms") or 0)
        if kind == "llm":
            usage = ev.get("usage") or {}
            tok = f"tok {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)}"
            err = " " + c.red("ERR " + ev["error"]) if ev.get("error") else ""
            print(f"  #{seq:<3} llm  {ev.get('model') or '?':<20} {dur:>8}  {tok}{err}")
        elif kind == "tool":
            err = " " + c.red(ev["error"]) if ev.get("error") else ""
            print(f"  #{seq:<3} tool {ev.get('name') or '?':<20} {dur:>8}{err}")
        elif kind == "log":
            print(f"  #{seq:<3} log  {c.dim(str(ev.get('message', '')))}{c.reset}")
        elif kind == "error":
            print(f"  #{seq:<3} {c.red('error ' + str(ev.get('error_type', '')) + ': ' + str(ev.get('message', '')))}{c.reset}")
        else:
            print(f"  #{seq:<3} {kind}")
    print()
    print(c.dim(f"inspect a step: backspin show {os.path.basename(args.file)} --step N") + c.reset)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    c = _color()
    a = load_run(args.a)
    b = load_run(args.b)
    report = diff_runs(a, b)
    _print_diff(report, c)
    return 0 if report.identical else 1


def _print_diff(report: DiffReport, c: C) -> None:
    ta, tb = report.totals_a, report.totals_b
    if report.identical:
        print(c.green("runs are identical (same steps, same LLM requests)") + c.reset)
    elif report.first_divergence is not None:
        print(
            c.yellow(f"runs diverge at step #{report.first_divergence}") + c.reset
        )
    else:
        print(c.yellow("same requests, different step counts") + c.reset)
    print(
        c.dim(
            f"tokens: {ta['total_tokens']} vs {tb['total_tokens']}  "
            f"duration: {_fmt_ms(ta['duration_ms'])} vs {_fmt_ms(tb['duration_ms'])}  "
            f"steps: {ta['steps']} vs {tb['steps']}"
        )
        + c.reset
    )
    print()
    print(f"{'#':>4}  {'kind':<5}  {'A':<28} {'B':<28} {'same':>5}")
    for s in report.steps:
        la = s.a["label"] if s.a else "-"
        lb = s.b["label"] if s.b else "-"
        if s.same is None:
            mark = c.red("solo")
        elif s.same:
            mark = c.green("yes")
        else:
            mark = c.red("NO")
        print(f"{s.index:>4}  {s.kind:<5}  {la:<28} {lb:<28} {mark}")


def cmd_ui(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("the viewer needs two extra packages:")
        print("  pip install 'backspin[ui]'")
        return 1
    from .server import create_app

    app = create_app(args.dir)
    print(f"backspin viewer  ->  http://{args.host}:{args.port}  (runs dir: {args.dir})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# --- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backspin",
        description="The flight recorder for AI agents: record, replay, diff.",
    )
    p.add_argument("--version", action="version", version=f"backspin {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("ls", help="list recorded runs in a directory")
    ls.add_argument("dir", nargs="?", default="runs", help="runs directory (default: runs)")
    ls.set_defaults(fn=cmd_ls)

    show = sub.add_parser("show", help="show one run's timeline")
    show.add_argument("file", help="path to a .backspin.jsonl run file")
    show.add_argument("--step", type=int, default=None, help="print one step as JSON")
    show.add_argument("--json", action="store_true", help="dump the whole run as JSON")
    show.set_defaults(fn=cmd_show)

    diff = sub.add_parser("diff", help="diff two runs; exits 1 when they differ")
    diff.add_argument("a", help="first run file")
    diff.add_argument("b", help="second run file")
    diff.set_defaults(fn=cmd_diff)

    ui = sub.add_parser("ui", help="launch the local timeline viewer")
    ui.add_argument("--dir", default="runs", help="runs directory (default: runs)")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8787)
    ui.set_defaults(fn=cmd_ui)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

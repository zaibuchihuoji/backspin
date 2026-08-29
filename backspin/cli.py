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
from .runfile import FILE_SUFFIX, load_run

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
    lineage = []
    if "replay_of" in meta:
        lineage.append(f"replay of {meta['replay_of']}")
    if "branch_of" in meta:
        lineage.append(f"branch of {meta['branch_of']}")
    lineage_s = f"  ({', '.join(lineage)})" if lineage else ""
    cost = f"  ~${t['cost_usd']:.4f}" + ("" if t.get("cost_complete") else "+")
    print(c.bold(f"run {run.run_id}") + f"  agent={run.agent}{lineage_s}{cost}")
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
        indent = "    " * (ev.get("depth") or 0)
        if kind == "llm":
            usage = ev.get("usage") or {}
            tok = f"tok {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)}"
            err = " " + c.red("ERR " + ev["error"]) if ev.get("error") else ""
            print(f"{indent}  #{seq:<3} llm  {ev.get('model') or '?':<20} {dur:>8}  {tok}{err}")
        elif kind == "tool":
            err = " " + c.red("ERR " + ev["error"]) if ev.get("error") else ""
            print(f"{indent}  #{seq:<3} tool {ev.get('name') or '?':<20} {dur:>8}{err}")
        elif kind == "span":
            phase = "enter" if ev.get("phase") == "enter" else "exit "
            err = " " + c.red("ERR " + ev["error"]) if ev.get("error") else ""
            print(
                f"{indent}  #{seq:<3} span {c.blue('[' + phase + '] ' + str(ev.get('name', '')))}"
                f"{c.reset}{dur:>8}{err}"
            )
        elif kind == "log":
            print(f"{indent}  #{seq:<3} log  {c.dim(str(ev.get('message', '')))}{c.reset}")
        elif kind == "error":
            etype = str(ev.get("error_type", ""))
            msg = str(ev.get("message", ""))
            print(f"{indent}  #{seq:<3} {c.red('error ' + etype + ': ' + msg)}{c.reset}")
        else:
            print(f"{indent}  #{seq:<3} {kind}")
    print()
    print(c.dim(f"inspect a step: backspin show {os.path.basename(args.file)} --step N") + c.reset)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    c = _color()
    a = load_run(args.a)
    b = load_run(args.b)
    report = diff_runs(a, b, llm_only=args.llm_only)
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


def cmd_branch(args: argparse.Namespace) -> int:
    c = _color()
    from .replay import branch as make_branch

    change: dict = {}
    if args.content is not None:
        change["content"] = args.content
    if args.tool_args:
        try:
            change["tool_arguments"] = json.loads(args.tool_args)
        except json.JSONDecodeError as exc:
            print(c.red(f"--tool-args is not valid JSON: {exc}") + c.reset)
            return 2
    if not change:
        print(c.red("nothing to mutate: pass --content and/or --tool-args") + c.reset)
        return 2

    path = make_branch(args.file, {args.step: change}, dir=args.dir)
    print(c.bold("branch run:") + f" {path}")
    print()
    report = diff_runs(load_run(args.file), load_run(path), llm_only=True)
    _print_diff(report, c)
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    if bool(args.upstream) == bool(args.replay):
        print("choose exactly one: --upstream URL (record) or --replay FILE (replay)")
        return 2
    try:
        import uvicorn
    except ImportError:
        print("proxy mode needs: pip install 'backspin[proxy]'")
        return 1
    from .proxy import create_proxy_app

    cassette = None
    if args.replay:
        from .replay import Cassette

        cassette = Cassette.from_run(load_run(args.replay))
    app = create_proxy_app(
        upstream=args.upstream, cassette=cassette, runs_dir=args.dir
    )
    mode = (
        f"replay of {os.path.basename(args.replay)}" if args.replay
        else f"record -> {args.upstream}"
    )
    print(f"backspin proxy [{mode}]")
    print(f"endpoint : http://{args.host}:{args.port}/v1  (point your agent's base_url here)")
    if cassette is None:
        print(f"recording: {app.state.recorder.path}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export import export

    text = export(load_run(args.file), fmt=args.format)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text)
    return 0


def cmd_share(args: argparse.Namespace) -> int:
    from .share import write_share_html

    out = write_share_html(args.file, args.out)
    print(f"shared viewer written to: {out}")
    print("send it to anyone — it opens in a browser, no install needed")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from .tui import run_tui

    run_tui(args.dir)
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
    diff.add_argument("--llm-only", action="store_true", help="align LLM calls only")
    diff.set_defaults(fn=cmd_diff)

    br = sub.add_parser("branch", help="what-if: replay a run with one answer mutated")
    br.add_argument("file", help="run file to branch from")
    br.add_argument("--step", type=int, required=True, help="0-based LLM-call index to mutate")
    br.add_argument("--content", default=None, help="replacement assistant content")
    br.add_argument(
        "--tool-args", default=None,
        help='replacement tool args as JSON, e.g. \'{"city": "Rome"}\'',
    )
    br.add_argument("--dir", default="runs", help="where to write the branch run")
    br.set_defaults(fn=cmd_branch)

    px = sub.add_parser("proxy", help="OpenAI-compatible local proxy: record or replay")
    px.add_argument("--upstream", default=None, help="record mode: e.g. https://api.openai.com")
    px.add_argument("--replay", default=None, help="replay mode: a recorded run file")
    px.add_argument("--dir", default="runs", help="where recorded runs are written")
    px.add_argument("--host", default="127.0.0.1")
    px.add_argument("--port", type=int, default=8840)
    px.set_defaults(fn=cmd_proxy)

    ex = sub.add_parser("export", help="export a run as a dataset (JSONL)")
    ex.add_argument("file", help="run file to export")
    ex.add_argument("--format", choices=["pairs", "sft"], default="pairs",
                    help="pairs: one line per LLM call; sft: one chat sample per run")
    ex.add_argument("-o", "--out", default=None, help="output file (default: stdout)")
    ex.set_defaults(fn=cmd_export)

    sh = sub.add_parser("share", help="bundle a run + viewer into one HTML file")
    sh.add_argument("file", help="run file to share")
    sh.add_argument("-o", "--out", default=None, help="output path (default: <run>.share.html)")
    sh.set_defaults(fn=cmd_share)

    tui = sub.add_parser("tui", help="keyboard-driven terminal viewer")
    tui.add_argument("--dir", default="runs", help="runs directory")
    tui.set_defaults(fn=cmd_tui)

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

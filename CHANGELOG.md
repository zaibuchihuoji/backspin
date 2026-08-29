# Changelog

All notable changes to backspin are documented here.

## 0.3.0 — 2026-08-29

The "real debugger" release: what-if branching, zero-code proxy
integration, structured spans, and costs.

- **What-if branching** — `Cassette.mutate()` alters a recorded answer;
  `backspin.replay.branch()` records the mutated replay as a new run
  (`branch_of` metadata), rewriting downstream requests so mutations
  propagate; `diff_runs(..., llm_only=True)` and
  `backspin branch <file> --step N --content "..."` pinpoint where the
  timelines split.
- **`backspin proxy`** — OpenAI-compatible local proxy in two modes:
  *record* (forward to upstream, capture everything, streaming included —
  zero-code integration for any framework/language) and *replay* (serve a
  recorded run back as an API, no network). Authorization headers are
  forwarded but never recorded.
- **Spans** — `with rec.span(name, meta=...)`: nested agent → tool →
  sub-LLM structure. Events carry `span_id`/`depth`; async-safe via
  contextvars (per-task stacks); exceptions recorded on the exit event;
  span durations excluded from run totals to avoid double counting.
- **Costs** — built-in per-1M-token price table (OpenAI, Claude, Gemini,
  DeepSeek; exact-then-longest-prefix matching), `cost_usd` /
  `cost_complete` in run totals, cost card in the viewer, `~$` in `show`.
- **pytest plugin** — `backspin` fixture (pytest11 entry point) with
  strict `assert_replays_identically()`: order-fallback replays are
  failures, only fingerprint-exact replay passes.
- **Viewer** — span tree indentation, cost card.
- **Docs** — `docs/format-spec.md` (the run file specification with
  versioning rules) and `docs/architecture.md`.
- Internal: diff signatures understand span events; `_usage_of` fixes
  streamed usage extraction; stream wrappers gain context-manager/close
  passthrough.

## 0.2.0 — 2026-08-29

Hardening release: the record → replay → diff → view loop is now verified
against the real OpenAI SDK and guarded by edge-case and performance tests.

- **Real-SDK integration suite** — a local OpenAI-compatible HTTP/SSE mock
  server runs the genuine `openai` SDK through sync, async, streaming
  (tool-call deltas, `include_usage`), context-manager and error paths.
  Found and fixed two real bugs:
  - async resource detection (modern SDKs ship async methods that are not
    coroutine functions — detection now uses the resource type name)
  - streamed `usage` chunks were dropped in stream reconstruction
- **Redaction API** — `Recorder(redact=...)` plus
  `backspin.redaction.redact_strings` / `mask`. Structural fields (model,
  tool name, fingerprint, durations) stay in clear; every other payload
  value — including unknown custom keys — goes through the redactor.
  Fingerprints are computed pre-redaction so replay matching is unaffected.
- **Streaming wrappers** now pass through `close()`, the async/with context
  manager protocols and positional args.
- **Performance guards** — 20k-event record/load and 2×4000-event diff stay
  in the seconds range.
- **Edge-case suite** — unicode round-trips, concurrent recorders,
  thread-safe single recorder, writes after close, circular references,
  empty cassettes, corrupt run files over the viewer API, CLI `--json`.
- **Packaging** — wheel verified to ship the viewer UI assets and
  `py.typed`.

## 0.1.0 — 2026-08-29

Initial MVP.

- `Recorder`: single-file JSONL run format (`.backspin.jsonl`), header +
  ordered steps, error capture with tracebacks, custom events
- OpenAI-shaped capture: sync / async / streaming, tool-call reconstruction
- `@rec.tool` decorator (sync + async)
- Deterministic replay: `Cassette`, `stub_client`, `patch_openai`
  (fingerprint match, order fallback with warning)
- `diff_runs`: step alignment by signature, first-divergence detection
- CLI: `backspin ls / show / diff / ui`
- Local viewer: FastAPI + zero-build vanilla JS (waterfall timeline, step
  inspector, side-by-side diff)
- `backspin.testing.FakeOpenAI` for keyless demos and tests

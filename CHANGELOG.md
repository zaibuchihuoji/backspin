# Changelog

All notable changes to backspin are documented here.

## 0.4.1 — 2026-08-29

- **Viewer i18n** — the local viewer is now Chinese-first with an EN/中文
  toggle in the header (choice persisted in localStorage); share files
  inherit the same interface. README screenshots updated.
- `share` also inlines the new `i18n.js` asset.

## 0.4.0 — 2026-08-29

Multi-provider release: Anthropic natively, TypeScript SDK, export/share/TUI.

- **Anthropic native** — `rec.capture_anthropic(client)`: sync/async/
  streaming capture of the Messages API (text + tool_use blocks), events
  recorded with `provider="anthropic"` and usage normalized to
  `prompt_tokens`/`completion_tokens` so costs/diffs work cross-provider.
  `backspin proxy` gains a `/v1/messages` adapter (record + replay,
  streaming included) — verified end-to-end against the real anthropic SDK.
- **TypeScript SDK** (`sdks/typescript`, `@backspin/sdk`) — Recorder with
  AsyncLocalStorage spans, `captureOpenAI` (sync/async/streaming),
  `Cassette`/`stubClient` replay, `diffRuns`. Same `.backspin.jsonl` run
  format — Python recordings replay in TypeScript and vice versa. 6 node:test
  suites.
- **Dataset export** — `backspin export <run> --format pairs|sft` turns
  recordings into eval/fine-tune JSONL.
- **Single-file sharing** — `backspin share <run>` bundles the run + the
  whole viewer into one HTML file; opens in any browser, zero install.
- **TUI** — `backspin tui`: keyboard-driven terminal viewer (runs → timeline
  → step JSON), injectable IO, fully unit-tested.
- Python suite: 104 tests; TypeScript suite: 6 tests.

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

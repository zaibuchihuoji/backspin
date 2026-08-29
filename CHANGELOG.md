# Changelog

All notable changes to backspin are documented here.

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

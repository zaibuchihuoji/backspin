# Architecture

backspin is deliberately small: one recorder, one file format, deterministic
replay, a differ, and two frontends (CLI + local web viewer). Everything
speaks the OpenAI chat-completions protocol shape, which is the de-facto
common denominator of LLM APIs.

```
                    ┌────────────────────────────────────────┐
                    │              your agent                │
                    │  (OpenAI SDK, any framework, any lang) │
                    └───┬────────────────────────┬───────────┘
                        │ capture_openai()       │ base_url → 127.0.0.1:8840
                        ▼                        ▼
              ┌──────────────────┐     ┌──────────────────┐
              │ Recorder         │     │ backspin proxy   │
              │  .span() .tool() │     │ record ⇄ replay  │
              │  log() event()   │     │ (httpx forward)  │
              └────────┬─────────┘     └────────┬─────────┘
                       ▼                        ▼
              ┌─────────────────────────────────────────┐
              │  *.backspin.jsonl   (one file per run)  │
              └───────┬──────────────┬──────────────────┘
                      ▼              ▼
             ┌──────────────┐  ┌────────────┐
             │ Cassette +   │  │ load_run → │
             │ stub_client  │  │ CLI / web  │
             │ patch_openai │  │ viewer     │
             └──────┬───────┘  └────────────┘
                    ▼
         ┌─────────────────────┐    ┌──────────────────────┐
         │ deterministic       │    │ diff_runs →          │
         │ replay / branch()   │    │ first divergence     │
         └─────────────────────┘    └──────────────────────┘
```

## Modules

| module | responsibility | deps |
|---|---|---|
| `runfile.py` | format: header + step events, `load_run`, fingerprints, totals | stdlib |
| `recorder.py` | `Recorder`: event emission, redaction, spans, tool decorator | stdlib |
| `integrations/openai.py` | capture of OpenAI-SDK-shaped clients (sync/async/stream) | none at import |
| `fakes.py` | duck-typed SDK stand-ins (`FakeResponse`, `stream_chunks`) | stdlib |
| `replay.py` | `Cassette`, `stub_client`, `patch_openai`, `branch` (what-if) | stdlib |
| `diff.py` | step alignment by signature, first-divergence report | stdlib |
| `cost.py` | per-model token price table, run cost report | stdlib |
| `proxy.py` | OpenAI-compatible local proxy: record/replay modes | fastapi, httpx |
| `cli.py` | `ls / show / diff / branch / proxy / ui` | stdlib (ui/proxy lazy) |
| `server.py` | local viewer API + static UI | fastapi |
| `ui/` | zero-build vanilla JS viewer | — |
| `testing.py` | `FakeOpenAI` scripted clients for demos/tests | stdlib |
| `pytest_plugin.py` | `backspin` fixture + strict replay assertion | pytest |

## Design invariants

1. **Recording never crashes the agent.** Serialization degrades to
   reprs; exceptions in recorded code are captured as events and
   re-raised; file output is created by `tempfile` inside a validated
   directory so concurrent recorders cannot collide or escape it.
2. **One run = one file.** Everything (CLI, viewer, replay, sharing) is
   built on the assumption that a run is self-contained.
3. **Replay matching is fingerprint-based** (model + messages, sorted-key
   JSON, SHA-256 prefix). Sampling params are excluded so replays survive
   them changing; the fallback (call order) warns loudly.
4. **Core stays stdlib-only.** fastapi/uvicorn/httpx are extras; every
   module imports them lazily inside its entry function.
5. **Readers ignore unknowns.** New event kinds and fields never break
   old consumers (see `docs/format-spec.md`).

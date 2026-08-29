# The backspin run format — specification

A backspin run is a single, self-contained, newline-delimited JSON file with
the extension `.backspin.jsonl`. One file = one agent run = one attachable
bug report. The format is deliberately boring: no schema registry, no
database — text you can `grep`.

- Encoding: UTF-8, one JSON object per line, `\n` line endings.
- Line 1 is the **header**. Every following line is a **step event**.
- Unknown fields and unknown event kinds MUST be ignored by readers, so old
  tools stay compatible with new recordings.
- `seq` is a monotonically increasing integer over step events (the header
  is not numbered). Order of lines = order of events.

## Header (line 1)

```json
{
  "kind": "header",
  "schema": 1,
  "run_id": "9f31c2ab77e0",
  "agent": "support-bot",
  "created_at": 1756448402.1,
  "backspin_version": "0.3.0",
  "metadata": {}
}
```

| field | required | notes |
|---|---|---|
| `kind` | yes | always `"header"` |
| `schema` | yes | format version, currently `1` |
| `run_id` | yes | 12-hex-char identifier, unique per recording |
| `agent` | yes | free-form label (separators stripped when used in filenames) |
| `created_at` | yes | unix seconds |
| `backspin_version` | yes | SDK version that wrote the file |
| `metadata` | no | free-form dict; `replay_of`, `branch_of`, `mutations`, `mode`, `upstream` are written by backspin itself |

## Common step-event fields

| field | present | notes |
|---|---|---|
| `kind` | yes | `llm` \| `tool` \| `log` \| `error` \| `span` \| custom |
| `seq` | yes | step number, starts at 1 |
| `ts` | yes | unix seconds at recording time |
| `duration_ms` | measured kinds | wall time of the recorded operation |
| `span_id` | inside a span | id of the innermost open span |
| `depth` | inside a span | nesting depth (0 = top level) |
| `fingerprint` | `llm` | 16-hex-char SHA-256 prefix over `{"model", "messages"}` (canonical JSON, sorted keys). Sampling parameters are deliberately excluded |
| `provider` | `llm` (non-OpenAI protocol) | e.g. `"anthropic"`; absent for OpenAI-protocol calls |
| `span_id` / `depth` | inside a span | see `span` below |

## `llm`

```json
{"kind": "llm", "seq": 3, "ts": 1756448402.1, "model": "gpt-4o-mini",
 "duration_ms": 812.4, "fingerprint": "9f31c2ab77e01d44",
 "request": {"model": "gpt-4o-mini", "messages": []},
 "response": {"choices": []},
 "usage": {"prompt_tokens": 120, "completion_tokens": 45},
 "error": "upstream HTTP 500: ..."}
```

`request`/`response` are OpenAI-protocol payloads (bodies of
`POST /v1/chat/completions` and its response). Reconstructed streamed
responses carry `"reconstructed_from_stream": true`. A failed call records
`error` and may omit `response`.

## `tool`

```json
{"kind": "tool", "seq": 4, "name": "get_weather",
 "args": {"args": ["Paris"], "kwargs": {}}, "result": "22C, sunny",
 "duration_ms": 3.2, "error": null}
```

## `log` / `error`

```json
{"kind": "log", "seq": 1, "level": "info", "message": "user asks: ..."}
{"kind": "error", "seq": 9, "message": "boom", "error_type": "RuntimeError",
 "traceback": "Traceback (most recent call last): ..."}
```

## `span`

Two events per span: `phase="enter"` (with `meta`) and `phase="exit"`
(with `duration_ms`, and `error`/`error_type` when the body raised).
`parent` is the enclosing span's id (`null` at top level). Non-span events
inside carry the innermost span's `span_id`/`depth`.

## Custom events

`rec.event("guardrail", verdict="blocked")` writes
`{"kind": "guardrail", ...payload}`. Consumers must tolerate any kind.

## Versioning rules

1. Additive changes (new fields, new kinds) bump nothing — readers ignore
   unknowns.
2. Breaking changes bump `schema` in the header AND the major version of
   backspin; `load_run` keeps reading the previous schema for one major
   version.
3. `fingerprint` inputs are frozen: `canonical_json({"model": model,
   "messages": messages})` with sorted keys, UTF-8, SHA-256, first 16 hex
   chars. If this ever changes, the field gets a new name.

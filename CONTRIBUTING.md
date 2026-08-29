# Contributing to backspin

Thanks for helping make agent debugging less painful.

## Setup

```bash
git clone <your fork>
cd backspin
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

`pytest` runs the full suite, including the real-SDK integration tests
(they talk to a local OpenAI-compatible mock server — no network, no API
key needed).

## Ground rules

- **Core stays dependency-free.** `backspin/` (except the `ui` extra)
  must import nothing beyond the standard library. If you need a library,
  it belongs in an extra or in the test suite.
- **A recorder must never crash the agent.** Serialization problems degrade
  to reprs; exceptions in recorded code are captured and re-raised. Keep it
  that way.
- **Every behavior change needs a test.** If it touches the run format,
  add a round-trip test (record → `load_run` → assert).
- **The run file format is a contract.** Bump `SCHEMA_VERSION` in
  `runfile.py` and document the change in `CHANGELOG.md` if you must break
  it — then keep `load_run` able to read old files.

## Style

- Type-hinted Python, `from __future__ import annotations`, 3.9+ compatible.
- ASCII-only CLI output (Windows consoles); unicode is fine in file content.
- Comments explain constraints, not mechanics.

## Submitting

1. Branch from `main`.
2. `pytest` green, including the integration and performance suites.
3. Update `CHANGELOG.md` under an "Unreleased" heading.
4. Open a PR describing the user-visible change.

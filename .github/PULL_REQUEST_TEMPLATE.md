## What & why

<!-- One or two sentences: what changes, and why a user would care. -->

## Checklist

- [ ] `pytest` green locally (including integration + performance suites)
- [ ] `ruff check backspin/ tests/` clean
- [ ] `mypy backspin/` clean
- [ ] Behavior change has a test (run-format changes need a round-trip test)
- [ ] `CHANGELOG.md` updated under an "Unreleased" heading
- [ ] No new core dependencies (`backspin/` stays stdlib-only outside extras)

<!-- If this touches the run file format: SCHEMA_VERSION bumped + load_run
     still reads old files. -->

---
name: Bug report
about: Something recorded / replayed / diffed wrong
labels: bug
---

**What happened?** A clear description of the wrong behavior.

**Minimal reproduction**

```python
# the smallest agent snippet that shows it
```

**The run file.** backspin is built so a bug report can be a `*.backspin.jsonl`
file — attach it when you can (redact first if it contains sensitive content,
see the README's redaction section). If not, include:

- backspin version (`pip show backspin`)
- Python version, OS
- how the run was captured: `capture_openai` / `capture_anthropic` / proxy / TS SDK
- provider and protocol (OpenAI-compatible / Anthropic Messages)

**What did you expect?**

**Anything else?** Tracebacks, warnings (`ReplayMismatchWarning`?), screenshots of the viewer.

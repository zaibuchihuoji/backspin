---
name: Feature request
about: Suggest a capability for the recorder / replay / diff workflow
labels: enhancement
---

**Your use case.** What are you trying to debug that backspin doesn't help with today?

**Proposed solution.** What should it do? An API sketch is welcome:

```python
# e.g. rec.capture_x(...) / backspin some-command ...
```

**Alternatives you considered.** Cloud tools, manual logging, etc.

**Does it fit the project's scope?** backspin stays local-first, file-based,
and dependency-free at its core — features that need a server or an account
belong elsewhere.

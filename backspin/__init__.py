"""backspin — the flight recorder for AI agents.

Record every LLM and tool call of an agent run to one portable file,
replay the run deterministically without any API access, and diff two
runs to find the exact step where behavior diverged.
"""
from .diff import DiffReport, StepDiff, diff_runs
from .recorder import Recorder
from .replay import (
    Cassette,
    ReplayMismatch,
    ReplayMismatchWarning,
    branch,
    patch_openai,
    stub_client,
)
from .runfile import FILE_SUFFIX, Run, load_run

__version__ = "0.4.1"

__all__ = [
    "Recorder",
    "Run",
    "load_run",
    "FILE_SUFFIX",
    "Cassette",
    "stub_client",
    "patch_openai",
    "branch",
    "ReplayMismatch",
    "ReplayMismatchWarning",
    "diff_runs",
    "DiffReport",
    "StepDiff",
    "__version__",
]

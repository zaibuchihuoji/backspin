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
    branch_agent,
    patch_openai,
    stub_client,
)
from .runfile import FILE_SUFFIX, Run, load_run

__version__ = "0.5.1"

__all__ = [
    "FILE_SUFFIX",
    "Cassette",
    "DiffReport",
    "Recorder",
    "ReplayMismatch",
    "ReplayMismatchWarning",
    "Run",
    "StepDiff",
    "__version__",
    "branch",
    "branch_agent",
    "diff_runs",
    "load_run",
    "patch_openai",
    "stub_client",
]

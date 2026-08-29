"""Compare two runs: where they diverged, and by how much.

Runs are aligned step by step. Each step gets a *signature* — what the
agent chose to do (LLM request fingerprint, tool name, log text) — so the
first mismatch marks the moment the two runs stopped doing the same thing.
Durations and token counts are reported as deltas, never compared.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .runfile import LLM, TOOL, Run


def _signature(ev: Dict[str, Any]) -> Tuple:
    kind = ev.get("kind")
    if kind == LLM:
        fp = ev.get("fingerprint")
        if fp is None:
            req = ev.get("request") or {}
            fp = str(req.get("messages"))
        return (LLM, fp)
    if kind == TOOL:
        return (TOOL, ev.get("name"))
    return (kind, ev.get("message") or ev.get("error_type"))


def _metrics(ev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if ev is None:
        return None
    usage = ev.get("usage") or {}
    label = ev.get("model") or ev.get("name") or (ev.get("message") or "")[:60]
    return {
        "label": label,
        "duration_ms": ev.get("duration_ms") or 0.0,
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "error": ev.get("error") or None,
    }


@dataclass
class StepDiff:
    index: int
    kind: str
    a: Optional[Dict[str, Any]]
    b: Optional[Dict[str, Any]]
    same: Optional[bool]  # None when the step exists on only one side


@dataclass
class DiffReport:
    a: Dict[str, Any]
    b: Dict[str, Any]
    steps: List[StepDiff] = field(default_factory=list)
    first_divergence: Optional[int] = None
    identical: bool = False

    @property
    def totals_a(self) -> Dict[str, Any]:
        return self.a["totals"]

    @property
    def totals_b(self) -> Dict[str, Any]:
        return self.b["totals"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "steps": [asdict(s) for s in self.steps],
            "first_divergence": self.first_divergence,
            "identical": self.identical,
        }


def diff_runs(a: Run, b: Run) -> DiffReport:
    """Diff two recorded runs of (nominally) the same agent."""
    sigs_a = [_signature(e) for e in a.events]
    sigs_b = [_signature(e) for e in b.events]
    n = max(len(a.events), len(b.events))

    steps: List[StepDiff] = []
    first_divergence: Optional[int] = None
    identical = len(a.events) == len(b.events)

    for i in range(n):
        ev_a = a.events[i] if i < len(a.events) else None
        ev_b = b.events[i] if i < len(b.events) else None
        same: Optional[bool] = None
        if ev_a is not None and ev_b is not None:
            same = sigs_a[i] == sigs_b[i]
        if same is False and first_divergence is None:
            first_divergence = i
        if same is not True:
            identical = False
        kind = (ev_a or ev_b or {}).get("kind", "?")
        steps.append(
            StepDiff(index=i, kind=kind, a=_metrics(ev_a), b=_metrics(ev_b), same=same)
        )

    return DiffReport(
        a=a.summary(),
        b=b.summary(),
        steps=steps,
        first_divergence=first_divergence,
        identical=identical,
    )

"""On-disk run format.

A run is a single self-contained ``*.backspin.jsonl`` file. The first line
is a header event; every following line is one recorded step — an LLM call,
a tool call, a log line, an error, or any custom event. Because a run is
one file, "please attach the failing run" becomes a practical bug-report
ritual instead of a database dump.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
FILE_SUFFIX = ".backspin.jsonl"

HEADER = "header"
LLM = "llm"
TOOL = "tool"
LOG = "log"
ERROR = "error"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def backspin_version() -> str:
    try:
        from importlib.metadata import version

        return version("backspin")
    except Exception:
        return "0.0.0+unknown"


def canonical_json(obj: Any) -> str:
    """Stable serialization, used for fingerprints."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )


def jsonable(obj: Any, max_len: int = 800) -> Any:
    """Return obj if JSON-serializable, else a truncated repr.

    A recorder must never crash the agent it is watching, so anything
    exotic degrades to a repr instead of raising.
    """
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return repr(obj)[:max_len]


def fingerprint_request(model: Optional[str], messages: Any) -> str:
    """Short stable fingerprint of an LLM request (model + messages).

    Sampling params (temperature, seed, ...) are deliberately excluded:
    replay matching should survive them changing.
    """
    payload = canonical_json({"model": model, "messages": messages})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_header(
    run_id: str, agent: str, metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "kind": HEADER,
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "agent": agent,
        "created_at": time.time(),
        "backspin_version": backspin_version(),
        "metadata": dict(metadata or {}),
    }


def _token_sums(events: List[Dict[str, Any]]) -> Dict[str, int]:
    prompt = completion = 0
    for e in events:
        usage = e.get("usage") or {}
        prompt += usage.get("prompt_tokens") or 0
        completion += usage.get("completion_tokens") or 0
    return {"prompt_tokens": prompt, "completion_tokens": completion}


@dataclass
class Run:
    """A loaded run file: header + ordered step events."""

    header: Dict[str, Any]
    events: List[Dict[str, Any]] = field(default_factory=list)
    path: Optional[str] = None

    @property
    def run_id(self) -> str:
        return str(self.header.get("run_id", ""))

    @property
    def agent(self) -> str:
        return str(self.header.get("agent", ""))

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self.header.get("metadata") or {})

    def by_kind(self, kind: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("kind") == kind]

    def llm_calls(self) -> List[Dict[str, Any]]:
        return self.by_kind(LLM)

    def tool_calls(self) -> List[Dict[str, Any]]:
        return self.by_kind(TOOL)

    def totals(self) -> Dict[str, Any]:
        tokens = _token_sums(self.events)
        duration = sum(e.get("duration_ms") or 0.0 for e in self.events)
        return {
            "steps": len(self.events),
            "llm_calls": len(self.llm_calls()),
            "tool_calls": len(self.tool_calls()),
            **tokens,
            "total_tokens": tokens["prompt_tokens"] + tokens["completion_tokens"],
            "duration_ms": round(duration, 1),
        }

    def summary(self) -> Dict[str, Any]:
        """Everything list views (CLI / viewer) need about a run."""
        return {
            "name": os.path.basename(self.path) if self.path else self.run_id,
            "run_id": self.run_id,
            "agent": self.agent,
            "created_at": self.header.get("created_at"),
            "backspin_version": self.header.get("backspin_version"),
            "metadata": self.metadata,
            "totals": self.totals(),
        }


def load_run(path: str) -> Run:
    """Load and validate a ``*.backspin.jsonl`` run file."""
    header: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(ev, dict) or "kind" not in ev:
                raise ValueError(f"{path}:{lineno}: event must be an object with a 'kind'")
            if header is None:
                if ev["kind"] != HEADER:
                    raise ValueError(f"{path}: first event must be a header")
                header = ev
            else:
                events.append(ev)
    if header is None:
        raise ValueError(f"{path}: empty run file")
    return Run(header=header, events=events, path=os.path.abspath(path))

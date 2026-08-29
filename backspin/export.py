"""Export recorded runs as training/eval datasets.

Two formats:

- ``pairs``  — one JSON line per LLM call: {"messages", "response", "model"}.
  Good for building eval sets from real traffic.
- ``sft``    — one JSON line per run: the final conversation
  ({"messages": [..., {"role": "assistant", ...}]}) in chat fine-tune style.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .runfile import Run


def _assistant_text(response: Any) -> str:
    """Extract plain assistant text from either protocol's response shape."""
    if not isinstance(response, dict):
        return ""
    if "choices" in response:  # OpenAI shape
        message = (response.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else ""
    if "content" in response:  # Anthropic shape
        parts = []
        for block in response.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


def export_pairs(run: Run) -> List[Dict[str, Any]]:
    rows = []
    for event in run.llm_calls():
        response = event.get("response")
        if not response:
            continue
        request = dict(event.get("request") or {})
        rows.append({
            "messages": request.get("messages") or [],
            "response": _assistant_text(response),
            "model": event.get("model"),
            "run_id": run.run_id,
            "seq": event.get("seq"),
        })
    return rows


def export_sft(run: Run) -> List[Dict[str, Any]]:
    calls = [e for e in run.llm_calls() if e.get("response")]
    if not calls:
        return []
    last = calls[-1]
    messages = list((last.get("request") or {}).get("messages") or [])
    messages = [dict(m) for m in messages]
    messages.append({"role": "assistant", "content": _assistant_text(last["response"])})
    return [{"messages": messages, "model": last.get("model"), "run_id": run.run_id}]


def export(run: Run, fmt: str = "pairs") -> str:
    """Export a run as JSONL text in the given format."""
    if fmt == "pairs":
        rows = export_pairs(run)
    elif fmt == "sft":
        rows = export_sft(run)
    else:
        raise ValueError(f"unknown export format: {fmt!r} (use 'pairs' or 'sft')")
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)

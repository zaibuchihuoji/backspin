"""Sensitive-data redaction for recordings.

Pass ``redact=`` to :class:`~backspin.Recorder` and every payload value is
transformed before it touches disk::

    from backspin import Recorder
    from backspin.redaction import mask, redact_strings

    rec = Recorder(
        agent="support-bot",
        redact=redact_strings(mask(r"sk-[A-Za-z0-9]{8,}")),
    )

Recordings still replay, but replayed values are the redacted ones — so
redact *before* you record and keep raw data out of files entirely.
LLM request fingerprints are computed from the raw request, so replay
matching is unaffected by redaction.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Union

Transform = Callable[[Any], Any]


def redact_strings(transform: Callable[[str], str]) -> Transform:
    """Build a deep redactor that applies ``transform`` to every string.

    Dict keys are preserved (only values pass through ``transform``);
    numbers, booleans and nested structures pass through recursively.
    """

    def deep(obj: Any) -> Any:
        if isinstance(obj, str):
            return transform(obj)
        if isinstance(obj, dict):
            return {k: deep(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [deep(v) for v in obj]
        return obj

    return deep


def mask(pattern: Union[str, "re.Pattern[str]"], repl: str = "[redacted]") -> Callable[[str], str]:
    """Build a string transform that replaces regex matches."""
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    return lambda s: compiled.sub(repl, s)

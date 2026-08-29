"""The flight recorder itself.

``Recorder`` writes events to a run file as they happen. It is designed to
be safe to wrap around code you do not trust: serialization problems
degrade to reprs, and exceptions in recorded code are captured as events
before being re-raised.
"""
from __future__ import annotations

import functools
import inspect
import json
import os
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional

from .runfile import (
    ERROR,
    FILE_SUFFIX,
    LLM,
    LOG,
    TOOL,
    fingerprint_request,
    jsonable,
    make_header,
    new_run_id,
)


# Fields that stay in clear even under a redactor: they are structural
# metadata the viewer, differ and replay matching rely on.
_STRUCTURAL_FIELDS = frozenset(
    {"model", "name", "duration_ms", "fingerprint", "error_type", "level"}
)


class Recorder:
    """Record an agent run to a single ``*.backspin.jsonl`` file.

    Usable as a context manager (records an error event if the body raises)
    or standalone — recording starts immediately in the constructor.

    Run files are created by :mod:`tempfile` inside ``dir`` with a unique
    generated name (see ``rec.path`` after construction), so concurrent
    recorders never collide and output can never land outside the resolved
    directory. ``base_dir`` lets embedding hosts further confine ``dir``
    under an allowed root.
    """

    def __init__(
        self,
        dir: str = "runs",
        *,
        agent: str = "agent",
        metadata: Optional[Dict[str, Any]] = None,
        base_dir: Optional[str] = None,
        redact: Optional[Callable[[Any], Any]] = None,
    ):
        self.run_id = new_run_id()
        self._redact = redact
        root = os.path.realpath(os.path.expanduser(dir))
        if base_dir is not None:
            allowed = os.path.realpath(os.path.expanduser(base_dir))
            if os.path.commonpath([root, allowed]) != allowed:
                raise ValueError(
                    f"directory {dir!r} is outside the allowed root {base_dir!r}"
                )
        os.makedirs(root, exist_ok=True)
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in agent)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self._lock = threading.Lock()
        self._seq = 0
        self._closed = False
        self._fp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=root,
            prefix=f"{stamp}-{slug}-{self.run_id}-",
            suffix=FILE_SUFFIX,
            delete=False,
            encoding="utf-8",
            newline="\n",
        )
        self.path = self._fp.name
        self._write_raw(make_header(self.run_id, agent, metadata))

    # -- plumbing ---------------------------------------------------------

    def _write_raw(self, ev: Dict[str, Any]) -> None:
        with self._lock:
            self._fp.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            self._fp.flush()

    def _write_line(self, ev: Dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            self._seq += 1
            ev["seq"] = self._seq
            self._fp.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            self._fp.flush()

    def _emit(self, kind: str, **payload: Any) -> Dict[str, Any]:
        ev: Dict[str, Any] = {"kind": kind, "ts": time.time()}
        ev.update({k: v for k, v in payload.items() if v is not None})
        if self._redact is not None:
            for key in ev:
                # Structural fields stay in clear: the viewer, the differ
                # and replay matching all depend on them. Everything else
                # (including unknown custom payload keys) goes through the
                # redactor.
                if key not in ("kind", "ts") and key not in _STRUCTURAL_FIELDS:
                    ev[key] = self._redact(ev[key])
        self._write_line(ev)
        return ev

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._fp.close()

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.record_error(exc)
        self.close()
        return False  # never swallow

    # -- recording API ------------------------------------------------------

    def log(self, message: str, level: str = "info", **extra: Any) -> None:
        """Record a free-form log line inside the run timeline."""
        self._emit(LOG, level=level, message=message, **jsonable(extra))

    def event(self, kind: str, **payload: Any) -> Dict[str, Any]:
        """Record a custom event kind (rendered as 'custom' in the viewer)."""
        return self._emit(kind, **jsonable(payload))

    def record_llm(
        self,
        *,
        request: Optional[Dict[str, Any]] = None,
        response: Optional[Any] = None,
        error: Optional[BaseException] = None,
        duration_ms: float = 0.0,
        model: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one LLM call. Prefer ``capture_openai`` over calling directly."""
        if model is None and request:
            model = request.get("model")
        fp = None
        if request and request.get("messages") is not None:
            fp = fingerprint_request(model, request.get("messages"))
        self._emit(
            LLM,
            duration_ms=round(duration_ms, 1),
            model=model,
            request=jsonable(request),
            response=jsonable(response, max_len=4000),
            usage=jsonable(usage),
            error=str(error) if error else None,
            fingerprint=fp,
            meta=jsonable(meta),
        )

    def record_tool(
        self,
        *,
        name: str,
        args: Optional[Dict[str, Any]] = None,
        result: Optional[Any] = None,
        error: Optional[BaseException] = None,
        duration_ms: float = 0.0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one tool call."""
        self._emit(
            TOOL,
            name=name,
            duration_ms=round(duration_ms, 1),
            args=jsonable(args),
            result=jsonable(result, max_len=4000),
            error=str(error) if error else None,
            meta=jsonable(meta),
        )

    def record_error(self, error: BaseException, **meta: Any) -> None:
        tb = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self._emit(
            ERROR,
            message=str(error),
            error_type=type(error).__name__,
            traceback=tb,
            **jsonable(meta),
        )

    # -- instrumentation helpers ---------------------------------------------

    def tool(self, fn: Callable) -> Callable:
        """Decorator: record every call to ``fn`` (sync or async) as a step."""

        def _record(name, args, kwargs, result=None, error=None, duration_ms=0.0):
            self.record_tool(
                name=name,
                args={"args": jsonable(list(args)), "kwargs": jsonable(dict(kwargs))},
                result=result,
                error=error,
                duration_ms=duration_ms,
            )

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    _record(fn.__name__, args, kwargs, error=exc,
                            duration_ms=(time.perf_counter() - t0) * 1000)
                    raise
                _record(fn.__name__, args, kwargs, result=result,
                        duration_ms=(time.perf_counter() - t0) * 1000)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                _record(fn.__name__, args, kwargs, error=exc,
                        duration_ms=(time.perf_counter() - t0) * 1000)
                raise
            _record(fn.__name__, args, kwargs, result=result,
                    duration_ms=(time.perf_counter() - t0) * 1000)
            return result

        return wrapper

    def capture_openai(self, client: Any) -> Any:
        """Patch ``client.chat.completions.create`` so every call is recorded.

        Works on the real ``openai.OpenAI`` / ``openai.AsyncOpenAI`` clients
        and on anything duck-type-shaped the same way (see
        :mod:`backspin.testing`). Returns the same client for chaining.
        """
        from .integrations.openai import capture_openai

        return capture_openai(self, client)

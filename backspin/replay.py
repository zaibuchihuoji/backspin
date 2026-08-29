"""Deterministic replay: run your agent again with recorded LLM responses.

A :class:`Cassette` indexes the LLM calls of a recorded run. A stub client
answers new calls from the cassette, matching by request fingerprint
(model + messages) and falling back to call order — so you can re-run the
agent offline, in tests, or against a fix, with the LLM held constant.

What-if branching: :meth:`Cassette.mutate` alters one recorded answer and
:func:`branch` records the mutated replay as a new run, so you can diff
"what would have happened if the model had said X".
"""
from __future__ import annotations

import copy
import json
import warnings
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Union

from .fakes import FakeResponse, stream_chunks
from .recorder import Recorder
from .runfile import Run, fingerprint_request, load_run


class ReplayMismatchWarning(UserWarning):
    """A replayed request did not exactly match its recording."""


class ReplayMismatch(Exception):
    """The cassette ran out of recordings before the replay finished."""


class Cassette:
    """Indexed recordings of LLM calls from one run."""

    def __init__(self, entries: List[Dict[str, Any]]):
        self.entries = entries
        self._cursor = 0

    @classmethod
    def from_run(cls, run: Run) -> "Cassette":
        return cls([e for e in run.llm_calls() if e.get("response") is not None])

    def __len__(self) -> int:
        return len(self.entries)

    def match(self, fingerprint: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Best-effort match against the remaining tape: exact fingerprint
        first, then the next recording in call order.

        Returns ``(entry, exact)``. ``entry`` is ``None`` when the cassette
        is exhausted. Matching is sequential — each recording is consumed
        at most once, so looping agents surface as exhaustion instead of
        silently looping the same response forever.
        """
        for i in range(self._cursor, len(self.entries)):
            if self.entries[i].get("fingerprint") == fingerprint:
                self._cursor = i + 1
                return self.entries[i], True
        if self._cursor < len(self.entries):
            entry = self.entries[self._cursor]
            self._cursor += 1
            return entry, False
        return None, False

    def take(self, fingerprint: str) -> Dict[str, Any]:
        """Like :meth:`match` but raises on exhaustion and warns on fallback."""
        entry, exact = self.match(fingerprint)
        if entry is None:
            raise ReplayMismatch(
                f"no recording left in cassette (wanted fingerprint {fingerprint})"
            )
        if not exact:
            warnings.warn(
                f"request fingerprint {fingerprint} not in cassette; "
                f"falling back to recording #{self._cursor} by call order",
                ReplayMismatchWarning,
                stacklevel=3,
            )
        return entry

    def mutate(
        self,
        index: int,
        *,
        content: Optional[str] = None,
        tool_arguments: Optional[Dict[str, Any]] = None,
    ) -> "Cassette":
        """What-if: return a copy with recording ``#index``'s answer altered.

        ``content`` replaces the assistant message text; ``tool_arguments``
        (a dict) replaces the first tool call's arguments, stored as JSON.
        Requests are untouched, so replay matching still works — only the
        answer the agent sees changes. Combine with :func:`branch` or
        ``stub_client`` to measure the downstream effect.
        """
        if not 0 <= index < len(self.entries):
            raise IndexError(
                f"recording #{index} out of range (cassette has {len(self.entries)})"
            )
        entries = copy.deepcopy(self.entries)
        resp = entries[index]["response"]
        if "choices" in resp:
            message = (resp["choices"] or [{}])[0].setdefault(
                "message", {"role": "assistant"}
            )
            if content is not None:
                message["content"] = content
            if tool_arguments is not None:
                calls = message.get("tool_calls")
                if not calls:
                    raise ValueError("that recording has no tool calls to mutate")
                calls[0].setdefault("function", {})["arguments"] = json.dumps(tool_arguments)
        elif "content" in resp:  # anthropic message: mutate first text block
            if tool_arguments is not None:
                raise ValueError(
                    "tool_arguments mutation is not supported for anthropic tool_use blocks yet"
                )
            for block in resp["content"] or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = content
                    break
            else:
                if content is not None:
                    resp.setdefault("content", []).append({"type": "text", "text": content})
        else:
            raise ValueError("unrecognized response shape; cannot mutate")
        return Cassette(entries)


class _StubCompletions:
    """Duck-typed ``chat.completions`` answered from a cassette."""

    def __init__(self, cassette: Cassette, *, async_mode: bool = False):
        self.cassette = cassette
        self.state = SimpleNamespace(calls=0, mismatches=[])
        self._async = async_mode

    def _respond(self, **kwargs: Any):
        self.state.calls += 1
        fp = fingerprint_request(kwargs.get("model"), kwargs.get("messages"))
        entry, exact = self.cassette.match(fp)
        if entry is None:
            raise ReplayMismatch(
                f"LLM call #{self.state.calls}: cassette exhausted "
                f"(fingerprint={fp})"
            )
        if not exact:
            self.state.mismatches.append(
                {"call": self.state.calls, "requested": fp,
                 "replayed": entry.get("fingerprint")}
            )
            warnings.warn(
                f"LLM call #{self.state.calls}: fingerprint mismatch, "
                f"replaying recording #{self.cassette._cursor} by call order",
                ReplayMismatchWarning,
                stacklevel=2,
            )
        data = dict(entry["response"])
        if kwargs.get("stream"):
            return iter(stream_chunks(data))
        return FakeResponse(data)

    def create(self, **kwargs: Any):
        if self._async:
            return self._respond_async(**kwargs)
        return self._respond(**kwargs)

    async def _respond_async(self, **kwargs: Any):
        return self._respond(**kwargs)


def stub_client(cassette: Cassette, *, async_mode: bool = False) -> SimpleNamespace:
    """A client shaped like ``openai.OpenAI`` (the slice agents touch)."""
    completions = _StubCompletions(cassette, async_mode=async_mode)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions), state=completions.state
    )


@contextmanager
def patch_openai(cassette: Cassette):
    """Patch ``openai.OpenAI`` / ``openai.AsyncOpenAI`` so constructors
    yield stub clients backed by ``cassette``. Restores on exit.

    Lets unmodified agent code (``client = OpenAI()``) replay offline.
    """
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "patch_openai() requires the openai package: pip install openai"
        ) from exc
    saved = (openai.OpenAI, openai.AsyncOpenAI)
    sync_client = stub_client(cassette)
    async_client = stub_client(cassette, async_mode=True)
    openai.OpenAI = lambda *a, **k: sync_client
    openai.AsyncOpenAI = lambda *a, **k: async_client
    try:
        yield SimpleNamespace(sync=sync_client, async_=async_client)
    finally:
        openai.OpenAI, openai.AsyncOpenAI = saved


def branch(
    run: Union[Run, str],
    mutations: Dict[int, Dict[str, Any]],
    *,
    dir: str = "runs",
    agent: Optional[str] = None,
) -> str:
    """What-if: record a replayed run with selected answers mutated.

    ``mutations`` maps a 0-based LLM-call index to
    :meth:`Cassette.mutate` kwargs, e.g. ``{1: {"content": "No."}}``. Every
    recorded LLM request is re-issued in order against the mutated cassette
    and captured into a new run file marked ``branch_of`` in its metadata.

    Returns the new run's path. Diff it against the original with
    ``diff_runs(original, branch, llm_only=True)`` — requests match until
    the mutated answer flows back into a later request, which is exactly
    where the two timelines split.
    """
    run_obj = load_run(run) if isinstance(run, str) else run
    if not mutations:
        raise ValueError("branch(): pass at least one mutation, e.g. {0: {'content': 'No.'}}")
    cassette = Cassette.from_run(run_obj)
    calls = run_obj.llm_calls()

    # Text substitutions that carry mutations forward: when a mutated answer
    # would have been fed back into a later request, rewrite that request's
    # assistant messages to the mutated text. (Content-level rewriting; tool
    # call arguments in follow-up requests are left as recorded.)
    substitutions: Dict[str, str] = {}
    for index in sorted(mutations):
        if not 0 <= index < len(calls):
            raise IndexError(
                f"mutation step {index} out of range (run has {len(calls)} LLM calls)"
            )
        before = (calls[index].get("response") or {}).get("choices", [{}])[0].get("message", {}).get("content")
        cassette = cassette.mutate(index, **mutations[index])
        after = (cassette.entries[index]["response"]["choices"][0]["message"].get("content"))
        if before is not None and after != before:
            substitutions[before] = after

    rec = Recorder(
        dir=dir,
        agent=agent or run_obj.agent,
        metadata={
            "branch_of": run_obj.run_id,
            "mutations": {str(k): v for k, v in sorted(mutations.items())},
        },
    )
    with rec:
        stub = rec.capture_openai(stub_client(cassette))
        with warnings.catch_warnings():
            # fingerprint fallbacks are the point of a branch: mutated
            # answers change later requests by design
            warnings.simplefilter("ignore", ReplayMismatchWarning)
            for entry in calls:
                if entry.get("response") is None:
                    continue
                request = dict(entry.get("request") or {})
                messages = [
                    dict(m, content=substitutions[m["content"]])
                    if m.get("role") == "assistant" and m.get("content") in substitutions
                    else m
                    for m in (request.get("messages") or [])
                ]
                stub.chat.completions.create(
                    model=request.get("model"), messages=messages
                )
    return rec.path


def branch_agent(
    fn: Callable,
    run: Union[Run, str],
    mutations: Dict[int, Dict[str, Any]],
    *,
    dir: str = "runs",
    agent: Optional[str] = None,
    extra_args: Optional[Tuple] = None,
) -> str:
    """Agent-level what-if: re-run the *actual agent function* against a
    mutated cassette and record it as a branch run.

    ``fn(client, rec, *extra_args)`` is your real agent function: ``client``
    is a stub answering from the (mutated) cassette, and ``rec`` is the
    branch run's recorder, so logs, spans, tool calls and downstream
    requests all happen for real and preserve the run's full shape (unlike
    :func:`branch`, which replays the request sequence only).

    Returns the new run's path; metadata carries ``branch_of`` +
    ``mutations``. Diff against the original with plain ``diff_runs`` —
    shapes align, and the first divergence is where the mutated answer
    changed the conversation.
    """
    run_obj = load_run(run) if isinstance(run, str) else run
    if not callable(fn):
        raise TypeError("branch_agent(): fn must be callable, taking (client, *extra_args)")
    if not mutations:
        raise ValueError("branch_agent(): pass at least one mutation, e.g. {0: {'content': 'No.'}}")
    cassette = Cassette.from_run(run_obj)
    for index in sorted(mutations):
        cassette = cassette.mutate(index, **mutations[index])

    rec = Recorder(
        dir=dir,
        agent=agent or run_obj.agent,
        metadata={
            "branch_of": run_obj.run_id,
            "mutations": {str(k): v for k, v in sorted(mutations.items())},
            "branch_level": "agent",
        },
    )
    with rec:
        stub = rec.capture_openai(stub_client(cassette))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ReplayMismatchWarning)
            fn(stub, rec, *(extra_args or ()))
    return rec.path

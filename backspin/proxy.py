"""OpenAI-compatible local proxy: record or replay, framework-agnostic.

Record mode — point any agent at the proxy instead of the vendor endpoint;
every request is forwarded upstream and captured into a run file::

    backspin proxy --upstream https://api.openai.com --port 8840
    # client: base_url = http://127.0.0.1:8840/v1

Replay mode — serve a recorded run back as an API, no upstream and no
network, from any language that speaks the OpenAI protocol::

    backspin proxy --replay runs/live.backspin.jsonl --port 8840

The proxy speaks streaming SSE on both paths: streamed upstream answers are
reconstructed into a recorded completion, and replays are streamed back as
chunks. Authorization headers are forwarded to upstream but never recorded.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .fakes import stream_chunks
from .replay import Cassette
from .recorder import Recorder
from .runfile import fingerprint_request


def _sse(obj: Any) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _acc_payload(acc: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild a completion-shaped dict from absorbed stream chunks."""
    message: Dict[str, Any] = {"role": "assistant"}
    if acc["content"]:
        message["content"] = "".join(acc["content"])
    if acc["tools"]:
        message["tool_calls"] = [acc["tools"][i] for i in sorted(acc["tools"])]
    return {
        "object": "chat.completion",
        "model": acc["model"],
        "reconstructed_from_stream": True,
        "choices": [{
            "index": 0,
            "finish_reason": acc["finish"] or "stop",
            "message": message,
        }],
        "usage": acc["usage"],
    }


def _absorb_chunk(acc: Dict[str, Any], chunk: Dict[str, Any]) -> None:
    """Accumulate one upstream SSE chunk (dict) into ``acc``."""
    if chunk.get("model"):
        acc["model"] = chunk["model"]
    if chunk.get("usage"):
        acc["usage"] = chunk["usage"]
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if delta.get("content"):
            acc["content"].append(delta["content"])
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = acc["tools"].setdefault(
                idx, {"id": "", "type": "function",
                      "function": {"name": "", "arguments": ""}}
            )
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
        if choice.get("finish_reason"):
            acc["finish"] = choice["finish_reason"]


def create_proxy_app(
    upstream: Optional[str] = None,
    cassette: Optional[Cassette] = None,
    runs_dir: str = "runs",
    agent: str = "proxy",
    metadata: Optional[Dict[str, Any]] = None,
) -> FastAPI:
    """Build the proxy app. Set ``upstream`` (record) or ``cassette``
    (replay) — exactly one.

    The recorder is available as ``app.state.recorder`` after creation.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "proxy mode requires httpx: pip install 'backspin[proxy]'"
        ) from exc

    if (upstream is None) == (cassette is None):
        raise ValueError(
            "create_proxy_app(): set exactly one of upstream= (record) or cassette= (replay)"
        )

    app = FastAPI(title="backspin proxy", docs_url=None, redoc_url=None)
    if upstream is not None:
        recorder = Recorder(
            dir=runs_dir, agent=agent,
            metadata={**(metadata or {}), "mode": "record", "upstream": upstream},
        )
        client = httpx.AsyncClient(
            base_url=upstream, timeout=httpx.Timeout(connect=15.0, read=600.0, write=600.0, pool=15.0)
        )
    else:
        recorder = Recorder(
            dir=runs_dir, agent=agent,
            metadata={**(metadata or {}), "mode": "replay"},
        )
        client = None
    app.state.recorder = recorder

    @app.get("/v1/models")
    async def models():
        if client is None:
            return JSONResponse({"object": "list", "data": []})
        resp = await client.get("/v1/models")
        return JSONResponse(resp.json(), status_code=resp.status_code)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        stream = body.get("stream", False)
        t0 = time.perf_counter()

        # ---- replay mode: answer from the cassette, no upstream ----------
        if client is None:
            fp = fingerprint_request(body.get("model"), body.get("messages"))
            entry, _exact = cassette.match(fp)
            if entry is None:
                raise HTTPException(
                    status_code=503,
                    detail="backspin replay proxy: cassette exhausted",
                )
            data = dict(entry["response"])
            if stream:
                async def replay_gen():
                    for chunk in stream_chunks(data):
                        yield _sse(chunk.model_dump())
                    yield "data: [DONE]\n\n"

                return StreamingResponse(replay_gen(), media_type="text/event-stream")
            return JSONResponse(data)

        # ---- record mode: forward upstream, capture the exchange ---------
        fwd_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() in ("authorization", "content-type", "accept")
        }
        ms = lambda: (time.perf_counter() - t0) * 1000

        if not stream:
            resp = await client.post("/v1/chat/completions", json=body, headers=fwd_headers)
            try:
                payload = resp.json()
            except Exception:
                payload = None
            if resp.status_code >= 400:
                recorder.record_llm(
                    request=body, model=body.get("model"), duration_ms=ms(),
                    error=RuntimeError(f"upstream HTTP {resp.status_code}: {resp.text[:300]}"),
                )
            else:
                recorder.record_llm(
                    request=body, response=payload,
                    usage=payload.get("usage") if payload else None,
                    model=(payload or {}).get("model") or body.get("model"),
                    duration_ms=ms(),
                )
            return JSONResponse(payload if payload is not None else {}, status_code=resp.status_code)

        upstream_resp = await client.send(
            client.build_request("POST", "/v1/chat/completions", json=body, headers=fwd_headers),
            stream=True,
        )
        if upstream_resp.status_code >= 400:
            raw = (await upstream_resp.aread()).decode("utf-8", "replace")
            await upstream_resp.aclose()
            recorder.record_llm(
                request=body, model=body.get("model"), duration_ms=ms(),
                error=RuntimeError(f"upstream HTTP {upstream_resp.status_code}: {raw[:300]}"),
            )
            return JSONResponse({"error": {"message": raw[:500]}}, status_code=upstream_resp.status_code)

        acc: Dict[str, Any] = {
            "content": [], "tools": {}, "usage": None,
            "finish": None, "model": body.get("model"),
        }

        async def passthrough_gen():
            try:
                async for line in upstream_resp.aiter_lines():
                    yield line + "\n"
                    stripped = line.strip()
                    if stripped.startswith("data:"):
                        data = stripped[5:].strip()
                        if data and data != "[DONE]":
                            try:
                                _absorb_chunk(acc, json.loads(data))
                            except json.JSONDecodeError:
                                pass
            finally:
                await upstream_resp.aclose()
                recorder.record_llm(
                    request=body, response=_acc_payload(acc), usage=acc["usage"],
                    model=acc["model"], duration_ms=ms(),
                )

        return StreamingResponse(passthrough_gen(), media_type="text/event-stream")

    return app


def serve_proxy(
    upstream: Optional[str] = None,
    cassette: Optional[Cassette] = None,
    runs_dir: str = "runs",
    host: str = "127.0.0.1",
    port: int = 8840,
) -> None:
    import uvicorn

    app = create_proxy_app(upstream=upstream, cassette=cassette, runs_dir=runs_dir)
    print(f"recording to: {app.state.recorder.path}")
    uvicorn.run(app, host=host, port=port, log_level="warning")

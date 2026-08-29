"""A local Anthropic-compatible HTTP server for integration tests.

Scripted by message content:
- message containing ``boom``   -> HTTP 400 error
- request with ``tools``        -> tool_use response (text + tool_use blocks)
- anything else                 -> echo message
Streaming requests get the full anthropic SSE event sequence.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from backspin.fakes import anthropic_stream_events


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _sse(event: dict) -> str:
    return "event: " + event.get("type", "message") + "\ndata: " + json.dumps(event) + "\n\n"


def make_anthropic_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/messages")
    async def messages(request: dict):
        model = request.get("model", "claude-fake")
        messages = request.get("messages", [])
        last = ""
        for m in reversed(messages):
            content = m.get("content")
            if isinstance(content, str):
                last = content
                break
            if isinstance(content, list):
                texts = [b.get("text", "") for b in content if isinstance(b, dict)]
                if any(texts):
                    last = " ".join(texts)
                    break
        usage = {"input_tokens": 21, "output_tokens": 13}
        cid = "msg_" + uuid.uuid4().hex[:8]

        if "boom" in last:
            return JSONResponse(
                status_code=400,
                content={"type": "error", "error": {
                    "type": "invalid_request_error", "message": "mock anthropic exploded",
                }},
            )

        if request.get("tools"):
            content = [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:8],
                 "name": "get_weather", "input": {"city": "Paris"}},
            ]
            stop_reason = "tool_use"
        else:
            content = [{"type": "text", "text": "echo: " + last}]
            stop_reason = "end_turn"

        message = {
            "id": cid, "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": usage,
        }

        if not request.get("stream"):
            return JSONResponse(message)

        def gen():
            for event in anthropic_stream_events(message):
                yield _sse(event)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def start_anthropic_server() -> str:
    """Start the mock anthropic server; return its origin (no /v1)."""
    config = uvicorn.Config(
        make_anthropic_app(), host="127.0.0.1", port=free_port(),
        log_level="error", lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("mock anthropic server failed to start")
    return f"http://127.0.0.1:{config.port}"

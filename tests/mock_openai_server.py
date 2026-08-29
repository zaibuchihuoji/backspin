"""A local OpenAI-compatible HTTP server for integration tests.

Runs the real openai SDK against real HTTP + real SSE parsing, with zero
external network. Scripted by message content:

- message mentioning ``weather`` + ``tools`` -> tool-call response
- message containing ``boom``               -> HTTP 500
- anything else                              -> echo completion

`weather` without tools streams a plain completion word by word.
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


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _sse(payload) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def completions(request: dict):
        model = request.get("model", "mock-gpt")
        messages = request.get("messages", [])
        last = str(messages[-1]["content"]) if messages else ""
        stream = request.get("stream", False)

        if "boom" in last:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": "mock server exploded", "type": "server_error"}},
            )

        wants_tool = bool(request.get("tools")) and "weather" in last
        usage = {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
        created = int(time.time())
        cid = "chatcmpl-" + uuid.uuid4().hex[:8]

        if wants_tool:
            tool_call = {
                "id": "call_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }
            if not stream:
                return JSONResponse({
                    "id": cid, "object": "chat.completion", "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                        "finish_reason": "tool_calls",
                    }],
                    "usage": usage,
                })
            base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}

            def tool_stream():
                yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": None}, "finish_reason": None}]})
                yield _sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": tool_call["id"], "type": "function",
                    "function": {"name": "get_weather", "arguments": ""},
                }]}, "finish_reason": None}]})
                for piece in ('{"city"', ': "Par', 'is"}'):
                    yield _sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{
                        "index": 0, "function": {"arguments": piece},
                    }]}, "finish_reason": None}]})
                yield _sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
                if request.get("stream_options", {}).get("include_usage"):
                    yield _sse({**base, "choices": [], "usage": usage})
                yield "data: [DONE]\n\n"

            return StreamingResponse(tool_stream(), media_type="text/event-stream")

        reply = "echo: " + last
        if not stream:
            return JSONResponse({
                "id": cid, "object": "chat.completion", "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }],
                "usage": usage,
            })

        base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}

        def text_stream():
            yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
            step = max(1, len(reply) // 3)
            for i in range(0, len(reply), step):
                yield _sse({**base, "choices": [{"index": 0, "delta": {"content": reply[i:i + step]}, "finish_reason": None}]})
            yield _sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            if request.get("stream_options", {}).get("include_usage"):
                yield _sse({**base, "choices": [], "usage": usage})
            yield "data: [DONE]\n\n"

        return StreamingResponse(text_stream(), media_type="text/event-stream")

    return app


def start_server() -> str:
    """Start the mock server on a free port; return its base_url."""
    return start_uvicorn(make_app())


def start_uvicorn(app) -> str:
    """Start any ASGI app on a free port; return its origin URL."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=free_port(), log_level="error", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server failed to start")
    return f"http://127.0.0.1:{config.port}"

"""FastAPI + WebSocket wrapper around the CLI agent."""

from __future__ import annotations

import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from server.bridge import stream_agent_reply

log = logging.getLogger("server.main")
logging.basicConfig(level=logging.INFO)
# Quiet the agent loop's per-token DEBUG spam.
logging.getLogger("agent.core.loop").setLevel(logging.INFO)
logging.getLogger("agent.tools").setLevel(logging.INFO)
logging.getLogger("agent.skills").setLevel(logging.WARNING)

app = FastAPI(title="CLI-Agent WebSocket Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    log.info("ws client connected")
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                await ws.send_json({"type": "error", "message": "expected json object"})
                continue
            if msg.get("type") != "user_msg":
                await ws.send_json({
                    "type": "error",
                    "message": f"unknown message type: {msg.get('type')!r}",
                })
                continue
            text = str(msg.get("text", ""))
            if not text:
                await ws.send_json({"type": "error", "message": "empty text"})
                continue

            try:
                async for evt in stream_agent_reply(text):
                    await ws.send_json(evt)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.exception("stream failed")
                try:
                    await ws.send_json({"type": "error", "message": str(e)})
                    await ws.send_json({"type": "done"})
                except Exception:
                    log.info("client gone before error could be sent")
                    return
    except WebSocketDisconnect:
        log.info("ws client disconnected")

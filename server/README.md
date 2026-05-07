# Server

FastAPI + WebSocket wrapper around the CLI agent. The browser front-end at
`http://localhost:5173` connects to `ws://localhost:8000/ws/chat`.

## Run

```bash
uv sync
uv run uvicorn server.main:app --reload --reload-dir server --port 8000
```

`--reload-dir server` keeps uvicorn's file watcher scoped to this directory.
Without it, the curator's writes under `src/agent/assistant_memory/...` would
trigger a reload mid-conversation and drop the WebSocket.

Health check: `curl http://localhost:8000/` -> `{"status":"ok"}`.

## Wire protocol

Client -> server (JSON over WebSocket):

```json
{"type": "user_msg", "text": "hello"}
```

Server -> client events:

- `{"type": "state", "state": "thinking|working|memory|idle"}`
- `{"type": "token", "text": "..."}` — streaming model output
- `{"type": "tool_call", "name": "...", "args": {...}}`
- `{"type": "tool_result", "name": "...", "result": "..."}`
- `{"type": "done"}`
- `{"type": "error", "message": "..."}`

## Modes

`server/bridge.py` tries to boot the real agent (settings + memory + skills +
tool registry). If anything fails (e.g. no `OPENAI_API_KEY` in `.env`) it falls
back to a stub that echoes + reverses the user's message so the pipeline can
still be tested end-to-end.

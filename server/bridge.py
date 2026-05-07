"""Bridge between the existing CLI agent and the WebSocket layer.

We wrap the synchronous `agent.core.loop.run_streaming` generator and convert
its `(event_type, data)` tuples into structured dict events suitable for a
browser front-end.

If real-agent initialization fails (e.g. missing API key, missing memory
directory, etc.) we fall back to a tiny echo stub so the front-end pipeline
can still be exercised end to end.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from pathlib import Path
from typing import AsyncIterator

_MARKER_OPEN = "[memory note:"
_MARKER_RE = re.compile(r"\[memory note:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)

log = logging.getLogger("server.bridge")

# Lazy / module-scope singletons. Initialized on first call.
_AGENT_READY: bool | None = None
_settings = None
_state = None
_memory = None
_skill_manager = None


def _try_init_agent() -> bool:
    """Attempt to initialize the real agent. Returns True on success."""
    global _AGENT_READY, _settings, _state, _memory, _skill_manager
    if _AGENT_READY is not None:
        return _AGENT_READY

    try:
        from agent.config.settings import load_settings
        from agent.core.state import ConversationState
        from agent.assistant_memory.manager import AssistantMemoryManager
        from agent.skills.discovery import discover_skills
        from agent.skills.manager import SkillManager
        from agent.tools import registry as tool_registry

        _settings = load_settings()

        memory_dir_raw = (
            os.environ.get("ASSISTANT_MEMORY_DIR")
            or os.environ.get("MEMORY_DIR")
            or "~/assistant-memory"
        )
        memory_dir = os.path.abspath(os.path.expanduser(memory_dir_raw))
        os.makedirs(memory_dir, exist_ok=True)
        _memory = AssistantMemoryManager(data_dir=memory_dir, settings=_settings)
        memory_context = _memory.on_startup()

        cwd = os.getcwd()
        _skill_manager = SkillManager(discover_skills(Path(cwd)))

        base_prompt = (
            "You are a helpful cli code assistant talking to the user via a "
            "browser front-end. Keep replies concise and well formatted in "
            "markdown.\n\n"
            "Memory marker convention: when the user reveals a STABLE, "
            "non-trivial fact worth remembering long-term (a preference, a "
            "person, an ongoing project, a decision, a deadline), include "
            "exactly one marker per fact in your reply formatted as "
            "`[memory note: <one concise sentence>]`. "
            "The marker is silently stripped from the message shown to the "
            "user — they will NOT see it. The system uses it to update "
            "long-term memory immediately. "
            "Do NOT add a marker for small talk, jokes, or things already "
            "documented. Each marker should describe one durable fact in "
            "natural language; the curator will route it to the right file."
        )
        parts = []
        if memory_context:
            parts.append(memory_context)
        if not _skill_manager.is_empty():
            parts.append(_skill_manager.catalog_xml())
        parts.append(base_prompt)
        system_prompt = "\n\n".join(parts)

        _state = ConversationState(system_prompt=system_prompt)
        tool_registry.init(_skill_manager, _state)

        _AGENT_READY = True
        log.info("Real agent initialized (model=%s)", _settings.model)
    except Exception as e:  # pragma: no cover - depends on env
        log.warning("Falling back to stub bridge — agent init failed: %s", e)
        _AGENT_READY = False
    return _AGENT_READY


async def _stub_reply(user_text: str) -> AsyncIterator[dict]:
    """Echo + reverse stub used when the real agent can't init."""
    yield {"type": "state", "state": "thinking"}
    await asyncio.sleep(0.1)
    yield {"type": "state", "state": "working"}
    reply = f"(stub) you said: {user_text}\nreversed: {user_text[::-1]}"
    for ch in reply:
        yield {"type": "token", "text": ch}
        await asyncio.sleep(0.01)
    yield {"type": "state", "state": "idle"}
    yield {"type": "done"}


async def _real_reply(user_text: str) -> AsyncIterator[dict]:
    """Drive the sync ReAct generator from a worker thread, surface events."""
    from agent.core.loop import run_streaming

    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _producer() -> None:
        sent_working = {"flag": False}
        # Streaming buffer state for marker stripping.
        # We hold tokens until we know they're not part of a `[memory note: ...]`.
        buf = {"pending": "", "in_marker": False, "visible": ""}

        def _ensure_working() -> None:
            if not sent_working["flag"]:
                sent_working["flag"] = True
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "state", "state": "working"}), loop
                )

        def _emit(text: str) -> None:
            if not text:
                return
            buf["visible"] += text
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "token", "text": text}), loop
            )

        def _fire_marker(note: str) -> None:
            """Trigger curator on a single completed marker — runs in its own thread."""
            if not _memory or not note:
                return
            curator = _memory.curator
            recent_snapshot = list(_memory.recent_turns)
            visible_so_far = buf["visible"]

            marker_id = f"mem-{int(loop.time() * 1000)}"

            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "state", "state": "memory"}), loop
            )
            asyncio.run_coroutine_threadsafe(
                queue.put({
                    "type": "curator_call",
                    "id": marker_id,
                    "note": note,
                }), loop,
            )

            def _run() -> None:
                try:
                    proposal = curator.propose_writes(
                        user_text,
                        f"{visible_so_far}\n[memory note: {note}]",
                        recent_snapshot,
                        signals={"explicit_notes": [note]},
                    )
                    writes = curator.apply_writes(proposal, confirm_callback=None)
                    curator.apply_manifest_updates(proposal.get("manifest_updates", []))
                    files = []
                    if isinstance(writes, list):
                        for w in writes:
                            if isinstance(w, dict) and w.get("path"):
                                files.append(w["path"])
                            elif isinstance(w, str):
                                files.append(w)
                    log.info("marker curator wrote: %s -> %s", note[:60], files)
                    asyncio.run_coroutine_threadsafe(
                        queue.put({
                            "type": "curator_result",
                            "id": marker_id,
                            "status": "ok",
                            "files": files,
                        }), loop,
                    )
                except Exception as exc:
                    log.warning("marker curator failed: %s", exc)
                    asyncio.run_coroutine_threadsafe(
                        queue.put({
                            "type": "curator_result",
                            "id": marker_id,
                            "status": "error",
                            "message": str(exc),
                        }), loop,
                    )

            threading.Thread(target=_run, daemon=True).start()

        def _process_delta(delta: str) -> None:
            """Append delta to buffer and emit non-marker portions to client."""
            buf["pending"] += delta
            while True:
                if not buf["in_marker"]:
                    idx = buf["pending"].find(_MARKER_OPEN)
                    if idx == -1:
                        # Safe-emit everything except a tail that could start the marker.
                        keep = min(len(_MARKER_OPEN) - 1, len(buf["pending"]))
                        if len(buf["pending"]) > keep:
                            _emit(buf["pending"][:-keep])
                            buf["pending"] = buf["pending"][-keep:]
                        break
                    if idx > 0:
                        _emit(buf["pending"][:idx])
                    buf["pending"] = buf["pending"][idx:]
                    buf["in_marker"] = True
                else:
                    close = buf["pending"].find("]")
                    if close == -1:
                        break  # wait for more tokens
                    marker_text = buf["pending"][: close + 1]
                    m = _MARKER_RE.search(marker_text)
                    if m:
                        _fire_marker(m.group(1).strip())
                    buf["pending"] = buf["pending"][close + 1 :]
                    buf["in_marker"] = False

        def _flush_remaining() -> None:
            """At stream end, emit any leftover buffer (e.g. an unclosed bracket)."""
            if buf["pending"]:
                _emit(buf["pending"])
                buf["pending"] = ""
                buf["in_marker"] = False

        try:
            # Optional: per-turn memory retrieval (mirrors CLI behavior).
            try:
                mem_block = _memory.retrieve_for_query(user_text) if _memory else ""
                if mem_block:
                    _state.set_transient_system_suffix(mem_block)
            except Exception as e:
                log.warning("memory retrieval failed: %s", e)

            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "state", "state": "thinking"}), loop
            )

            for event_type, data in run_streaming(user_text, _settings, state=_state):
                if event_type == "content_delta":
                    _ensure_working()
                    _process_delta(data.get("delta", ""))
                elif event_type == "tool_call":
                    name = str(data.get("name", ""))
                    state = "memory" if "memory" in name.lower() else "working"
                    sent_working["flag"] = False
                    asyncio.run_coroutine_threadsafe(
                        queue.put({"type": "state", "state": state}), loop
                    )
                    asyncio.run_coroutine_threadsafe(
                        queue.put({
                            "type": "tool_call",
                            "name": data.get("name"),
                            "args": data.get("args"),
                        }), loop,
                    )
                elif event_type == "tool_result":
                    asyncio.run_coroutine_threadsafe(
                        queue.put({
                            "type": "tool_result",
                            "name": data.get("name"),
                            "result": data.get("result"),
                        }), loop,
                    )
                elif event_type == "done":
                    _flush_remaining()
                    visible_text = buf["visible"]
                    try:
                        if _memory:
                            _memory.on_user_turn(user_text)
                            # Don't run curator at done — markers (if any) already
                            # fired curator mid-stream. Just update turn state.
                            _memory.on_assistant_turn(visible_text, run_curator=False)
                    except Exception as e:
                        log.warning("memory turn-hook failed: %s", e)
                    asyncio.run_coroutine_threadsafe(
                        queue.put({"type": "state", "state": "idle"}), loop
                    )
                    asyncio.run_coroutine_threadsafe(
                        queue.put({"type": "done"}), loop
                    )
        except Exception as e:
            log.exception("agent producer failed")
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "error", "message": str(e)}), loop
            )
            asyncio.run_coroutine_threadsafe(queue.put({"type": "done"}), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    await loop.run_in_executor(None, lambda: None)  # ensure executor is up
    fut = loop.run_in_executor(None, _producer)

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        # Ensure the producer thread is reaped.
        try:
            await fut
        except Exception:
            pass


async def stream_agent_reply(user_text: str) -> AsyncIterator[dict]:
    """Yield structured events for one user message.

    Event shapes:
      {"type": "state", "state": "thinking|working|memory|idle"}
      {"type": "token", "text": str}
      {"type": "tool_call", "name": str, "args": dict}
      {"type": "tool_result", "name": str, "result": str}
      {"type": "done"}
      {"type": "error", "message": str}
    """
    if _try_init_agent():
        async for evt in _real_reply(user_text):
            yield evt
    else:
        async for evt in _stub_reply(user_text):
            yield evt

"""Signal detector — cheap parallel pass on user message arrival.

Runs on the *user* side (before the assistant responds) so retrieval can use
detected entities as hints and the post-assistant curator can skip
re-discovery. NEVER blocks the main loop — callers should spawn this in a
daemon thread.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from agent.config.settings import Settings
from agent.llm.client import create_client

from .prompts import SIGNAL_DETECTOR_PROMPT
from .schema import pick_model
from .store import AssistantMemoryStore


logger = logging.getLogger(__name__)


_DETECT_TIMEOUT_S = 10.0
_MAX_RECENT_TURNS = 3
_EMPTY: dict[str, list] = {
    "entities": [],
    "intentions": [],
    "events": [],
    "preferences": [],
    "corrections": [],
}


def _safe_brace(s: Any) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("{", "{{").replace("}", "}}")


def _format_recent_turns(recent_turns: list[dict]) -> str:
    if not recent_turns:
        return "(none)"
    tail = recent_turns[-_MAX_RECENT_TURNS:]
    out: list[str] = []
    for turn in tail:
        role = turn.get("role", "")
        content = turn.get("content", "")
        out.append(f"{role}: {content}")
    return "\n".join(out)


def _empty_signals() -> dict[str, list]:
    return {k: [] for k in _EMPTY}


class SignalDetector:
    """Extract structured signals from a user message via the flash model."""

    def __init__(self, store: AssistantMemoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.client = create_client(settings)
        self.model_flash = pick_model(settings, prefer="flash")

    def detect(self, user_msg: str, recent_turns: list[dict]) -> dict:
        if not user_msg or not user_msg.strip():
            return _empty_signals()

        prompt = SIGNAL_DETECTOR_PROMPT.format(
            recent_turns=_safe_brace(_format_recent_turns(recent_turns)),
            user_msg=_safe_brace(user_msg),
        )

        result_box: dict[str, Any] = {"content": None, "error": None}

        def _call() -> None:
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_flash,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                result_box["content"] = resp.choices[0].message.content or ""
            except Exception as exc:  # pragma: no cover - network/client errors
                result_box["error"] = exc

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        worker.join(timeout=_DETECT_TIMEOUT_S)
        if worker.is_alive():
            logger.warning("signal detector LLM call timed out after %.1fs", _DETECT_TIMEOUT_S)
            return _empty_signals()
        if result_box["error"] is not None:
            logger.warning("signal detector LLM call failed: %s", result_box["error"])
            return _empty_signals()

        content = result_box["content"] or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("signal detector returned non-JSON: %s", exc)
            return _empty_signals()
        if not isinstance(data, dict):
            return _empty_signals()

        out = _empty_signals()
        for key in out:
            val = data.get(key)
            if isinstance(val, list):
                out[key] = val
        return out

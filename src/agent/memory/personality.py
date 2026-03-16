"""Personality feedback extraction and soul patching from session conversations."""

import json
import re

from agent.logger import get_logger
from agent.memory.llm import LLMClient
from agent.memory.models import ActiveSession, Personality
from agent.memory.prompts import (
    SOUL_FEEDBACK_SYSTEM,
    SOUL_FEEDBACK_USER,
    SOUL_MERGE_SYSTEM,
    SOUL_MERGE_USER,
)

log = get_logger(__name__)


def extract_feedback(session: ActiveSession, llm: LLMClient) -> list[str]:
    """Extract soul updates (preferences + emergent quirks) from session. Returns [] on empty/failure."""
    if not session.messages:
        return []

    conversation = "\n".join(
        f"{m['role']}: {m['content']}" for m in session.messages
    )
    user_msg = SOUL_FEEDBACK_USER.replace("{conversation}", conversation)

    try:
        response = llm.complete(system=SOUL_FEEDBACK_SYSTEM, user=user_msg)
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            return []
        parsed = json.loads(match.group())
        prefs = parsed.get("preferences", [])
        if not isinstance(prefs, list):
            return []
        return [p.strip() for p in prefs if p.strip()]
    except Exception:
        return []


def patch_soul(
    personality: Personality, new_preferences: list[str], llm: LLMClient
) -> Personality:
    """Merge new preferences into personality soul. Returns unchanged on empty prefs or failure."""
    if not new_preferences:
        return personality

    try:
        existing = personality.soul
        new_prefs_text = "\n".join(new_preferences)
        user_msg = (
            SOUL_MERGE_USER.replace("{existing_soul}", existing)
            .replace("{new_preferences}", new_prefs_text)
        )
        merged_soul = llm.complete(
            system=SOUL_MERGE_SYSTEM, user=user_msg
        ).strip()
        # Enforce 300-word limit (keep first 300 whitespace-separated tokens)
        words = [w for w in merged_soul.split() if w]
        if len(words) > 300:
            merged_soul = " ".join(words[:300])
        return Personality(
            soul=merged_soul,
            immutable_core=personality.immutable_core,
        )
    except Exception as e:
        log.exception("patch_soul failed: %s", e)
        return personality

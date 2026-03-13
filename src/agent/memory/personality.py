"""Personality feedback extraction and soul patching from session conversations."""

import json
import re

from agent.logger import get_logger
from agent.memory.digest import merge_learnings
from agent.memory.llm import LLMClient
from agent.memory.models import ActiveSession, Personality
from agent.memory.prompts import SOUL_FEEDBACK_SYSTEM, SOUL_FEEDBACK_USER

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
        new_learnings = "\n".join(new_preferences)
        merged_soul = merge_learnings(existing, new_learnings, llm)
        return Personality(
            soul=merged_soul,
            immutable_core=personality.immutable_core,
        )
    except Exception as e:
        log.exception("patch_soul failed: %s", e)
        return personality

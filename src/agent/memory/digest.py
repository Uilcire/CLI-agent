"""LLM-powered digest generation and learning merge."""

import json
import re
from datetime import UTC, datetime

from agent.logger import get_logger
from agent.memory.llm import LLMClient
from agent.memory.models import ActiveSession, SessionDigest
from agent.memory.prompts import (
    LEARNING_MERGE_SYSTEM,
    LEARNING_MERGE_USER,
    SESSION_DIGEST_SYSTEM,
    SESSION_DIGEST_USER,
)

log = get_logger(__name__)


def derive_digest(session: ActiveSession, llm: LLMClient) -> SessionDigest:
    """Generate a SessionDigest from session messages via LLM. Returns fallback on empty or failure."""
    project_id = session.project_id or ""

    if not session.messages:
        return SessionDigest(
            session_id=session.session_id,
            project_id=project_id,
            timestamp=datetime.now(UTC).isoformat(),
            summary="Empty session — no messages recorded.",
            capabilities=[],
            learnings="",
        )

    conversation = "\n".join(
        f"{m['role']}: {m['content']}" for m in session.messages
    )
    user_msg = SESSION_DIGEST_USER.replace("{conversation}", conversation)

    def _parse_response(response: str) -> dict | None:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group())
            if "summary" not in parsed:
                return None
            return parsed
        except json.JSONDecodeError:
            return None

    fallback_failed = SessionDigest(
        session_id=session.session_id,
        project_id=project_id,
        timestamp=datetime.now(UTC).isoformat(),
        summary="Session digest generation failed.",
        capabilities=[],
        learnings="",
    )

    for attempt in range(2):
        response = llm.complete(system=SESSION_DIGEST_SYSTEM, user=user_msg)
        parsed = _parse_response(response)
        if parsed is not None:
            break
        if attempt == 1:
            return fallback_failed

    summary = parsed.get("summary", "") or ""
    capabilities = parsed.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    learnings = parsed.get("learnings", "") or ""

    return SessionDigest(
        session_id=session.session_id,
        project_id=project_id,
        timestamp=datetime.now(UTC).isoformat(),
        summary=summary,
        capabilities=capabilities,
        learnings=learnings,
    )


def merge_learnings(
    existing: str, new_learnings: str, llm: LLMClient
) -> str:
    """Merge new learnings into existing via LLM. Returns concat fallback on error."""
    existing_stripped = existing.strip()
    new_stripped = new_learnings.strip()

    if not existing_stripped and not new_stripped:
        return ""
    if not existing_stripped:
        return new_stripped
    if not new_stripped:
        return existing_stripped

    user_msg = (
        LEARNING_MERGE_USER.replace("{existing_learnings}", existing_stripped)
        .replace("{new_learnings}", new_stripped)
    )

    try:
        return llm.complete(
            system=LEARNING_MERGE_SYSTEM, user=user_msg
        ).strip()
    except Exception as e:
        log.exception("merge_learnings failed: %s", e)
        return f"{existing_stripped}\n{new_stripped}"

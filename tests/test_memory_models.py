"""Tests for memory Pydantic models."""

import pytest
from pydantic import ValidationError

from agent.memory.models import ActiveSession, Personality, Project, SessionDigest


def test_personality_roundtrip() -> None:
    """Round-trip: construct, model_dump_json(), model_validate_json(), assert equal."""
    p = Personality(soul="helpful", immutable_core="honest")
    json_str = p.model_dump_json()
    restored = Personality.model_validate_json(json_str)
    assert restored == p


def test_project_roundtrip() -> None:
    """Round-trip for Project."""
    proj = Project(
        project_id="abc123",
        description="Test",
        status="active",
    )
    json_str = proj.model_dump_json()
    restored = Project.model_validate_json(json_str)
    assert restored == proj


def test_session_digest_roundtrip() -> None:
    """Round-trip for SessionDigest."""
    d = SessionDigest(
        session_id="s1",
        project_id="p1",
        timestamp="2025-01-01T12:00:00",
        summary="Did stuff",
    )
    json_str = d.model_dump_json()
    restored = SessionDigest.model_validate_json(json_str)
    assert restored == d


def test_active_session_roundtrip() -> None:
    """Round-trip for ActiveSession."""
    s = ActiveSession(
        session_id="s1",
        project_id="p1",
        messages=[{"role": "user", "content": "hi"}],
    )
    json_str = s.model_dump_json()
    restored = ActiveSession.model_validate_json(json_str)
    assert restored == s


def test_personality_immutable_core_raises() -> None:
    """immutable_core cannot be modified after initialization."""
    p = Personality(soul="helpful", immutable_core="honest")
    with pytest.raises(AttributeError):
        p.immutable_core = "new"  # type: ignore[misc]


def test_project_status_rejects_invalid() -> None:
    """Project.status rejects invalid values."""
    with pytest.raises(ValidationError):
        Project(
            project_id="x",
            description="Test",
            status="unknown",  # type: ignore[arg-type]
        )


def test_personality_soul_is_mutable() -> None:
    """soul on Personality is writable (only immutable_core is locked)."""
    p = Personality(soul="helpful", immutable_core="honest")
    p.soul = "very helpful"
    assert p.soul == "very helpful"

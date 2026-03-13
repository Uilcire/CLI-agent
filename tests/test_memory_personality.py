"""Tests for extract_feedback and patch_soul. Use MockLLMClient, no real API calls."""

import pytest

from agent.memory.models import ActiveSession, Personality
from agent.memory.personality import extract_feedback, patch_soul
from agent.memory.llm import MockLLMClient


def test_extract_feedback_no_preferences() -> None:
    """Mock returns empty preferences — result is []."""
    mock = MockLLMClient('{"preferences": []}')
    session = ActiveSession(
        session_id="s1",
        project_id="",
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    result = extract_feedback(session, mock)
    assert result == []


def test_extract_feedback_finds_preferences() -> None:
    """Mock returns preferences — assert result matches."""
    mock = MockLLMClient('{"preferences": ["be concise", "use type hints"]}')
    session = ActiveSession(
        session_id="s1",
        project_id="",
        messages=[
            {"role": "user", "content": "be concise"},
            {"role": "assistant", "content": "ok"},
        ],
    )
    result = extract_feedback(session, mock)
    assert result == ["be concise", "use type hints"]


def test_extract_feedback_empty_session() -> None:
    """ActiveSession with no messages — returns [] without calling LLM."""

    class RaiseIfCalled:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM should not be called for empty session")

    session = ActiveSession(session_id="empty", project_id="", messages=[])
    result = extract_feedback(session, RaiseIfCalled())
    assert result == []


def test_extract_feedback_parse_failure_returns_empty() -> None:
    """Mock returns non-JSON — returns [], does not raise."""
    mock = MockLLMClient("not json")
    session = ActiveSession(
        session_id="s1",
        project_id="",
        messages=[{"role": "user", "content": "hi"}],
    )
    result = extract_feedback(session, mock)
    assert result == []


def test_patch_soul_no_preferences() -> None:
    """patch_soul(personality, [], mock) returns same personality, LLM not called."""

    class RaiseIfCalled:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM should not be called when prefs empty")

    p = Personality(soul="Be helpful.", immutable_core="Be honest.")
    result = patch_soul(p, [], RaiseIfCalled())
    assert result is p
    assert result.soul == "Be helpful."
    assert result.immutable_core == "Be honest."


def test_patch_soul_merges_preferences() -> None:
    """Merges new preferences into soul via merge_learnings."""
    p = Personality(soul="Be helpful.", immutable_core="Be honest.")
    new_preferences = ["be concise", "use type hints"]
    mock = MockLLMClient("Be helpful and concise. Always use type hints.")
    result = patch_soul(p, new_preferences, mock)
    assert result.soul == "Be helpful and concise. Always use type hints."
    assert result.immutable_core == "Be honest."


def test_patch_soul_llm_failure_returns_unchanged() -> None:
    """Mock raises — merge_learnings catches and returns concat fallback; patch_soul gets valid result, no raise."""
    # merge_learnings swallows LLM exceptions and returns concat, so patch_soul receives that and builds new Personality.
    # Verifies we don't raise; result is a valid merged personality (merge fallback).

    class RaiseMock:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM error")

    p = Personality(soul="original", immutable_core="core")
    result = patch_soul(p, ["new pref"], RaiseMock())
    # merge_learnings fallback: "original" + "\n" + "new pref"
    assert result.soul == "original\nnew pref"
    assert result.immutable_core == "core"


def test_patch_soul_immutable_core_preserved() -> None:
    """Patch soul several times — immutable_core never changes."""
    p = Personality(soul="Soul v1", immutable_core="Core never changes")
    mock = MockLLMClient("merged soul")

    r1 = patch_soul(p, ["pref1"], mock)
    assert r1.immutable_core == "Core never changes"

    r2 = patch_soul(r1, ["pref2"], mock)
    assert r2.immutable_core == "Core never changes"
    assert r2 is not r1  # New Personality instance
    assert r2.immutable_core == p.immutable_core

"""Tests for derive_digest and merge_learnings. Use MockLLMClient, no real API calls."""

import pytest

from agent.memory.digest import derive_digest, merge_learnings
from agent.memory.llm import MockLLMClient
from agent.memory.models import ActiveSession


def test_derive_digest_valid_response() -> None:
    """Valid JSON response produces correct digest."""
    response = '{"summary": "User asked about Python.", "capabilities": ["python"], "learnings": "User is a beginner."}'
    session = ActiveSession(
        session_id="abc123",
        project_id="p1",
        messages=[
            {"role": "user", "content": "How do I loop?"},
            {"role": "assistant", "content": "Use a for loop."},
        ],
    )
    digest = derive_digest(session, MockLLMClient(response))

    assert digest.summary == "User asked about Python."
    assert digest.capabilities == ["python"]
    assert digest.learnings == "User is a beginner."
    assert digest.session_id == session.session_id
    assert digest.timestamp
    assert len(digest.timestamp) > 0


def test_derive_digest_retries_on_invalid_json() -> None:
    """First call returns invalid, second returns valid JSON — succeeds after retry."""

    class ToggleMock:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system: str, user: str) -> str:
            self.calls += 1
            if self.calls == 1:
                return "not json"
            return '{"summary": "ok", "capabilities": [], "learnings": ""}'

    session = ActiveSession(
        session_id="x",
        project_id="",
        messages=[{"role": "user", "content": "hi"}],
    )
    toggle = ToggleMock()
    digest = derive_digest(session, toggle)

    assert digest.summary == "ok"
    assert toggle.calls == 2


def test_derive_digest_fallback_on_double_failure() -> None:
    """Both attempts return invalid JSON — returns fallback digest, does not raise."""
    session = ActiveSession(
        session_id="x",
        project_id="",
        messages=[{"role": "user", "content": "hi"}],
    )
    digest = derive_digest(session, MockLLMClient("not valid json"))

    assert digest.summary == "Session digest generation failed."
    assert digest.learnings == ""


def test_derive_digest_empty_session_returns_fallback() -> None:
    """Empty session returns fallback — no LLM call (mock would raise if called)."""

    class RaiseIfCalled:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM should not be called for empty session")

    session = ActiveSession(session_id="empty", project_id="", messages=[])
    digest = derive_digest(session, RaiseIfCalled())

    assert digest.summary == "Empty session — no messages recorded."
    assert digest.session_id == "empty"


def test_derive_digest_handles_json_with_extra_prose() -> None:
    """Response with leading/trailing prose — regex extraction works."""
    response = 'Here is your JSON:\n{"summary": "Done.", "capabilities": [], "learnings": "x"}\nHope this helps!'
    session = ActiveSession(
        session_id="s1",
        project_id="",
        messages=[{"role": "user", "content": "test"}],
    )
    digest = derive_digest(session, MockLLMClient(response))

    assert digest.summary == "Done."
    assert digest.learnings == "x"


def test_merge_learnings_both_empty() -> None:
    """Both empty — returns empty string (no LLM call)."""
    mock = MockLLMClient("should not matter")
    result = merge_learnings("", "", mock)
    assert result == ""


def test_merge_learnings_existing_empty() -> None:
    """Existing empty — returns new without calling LLM."""
    result = merge_learnings("", "new stuff", MockLLMClient("ignored"))
    assert result == "new stuff"


def test_merge_learnings_new_empty() -> None:
    """New empty — returns existing without calling LLM."""
    result = merge_learnings("existing", "", MockLLMClient("ignored"))
    assert result == "existing"


def test_merge_learnings_calls_llm_when_both_present() -> None:
    """Both present — calls LLM and returns merged result."""
    result = merge_learnings("old", "new", MockLLMClient("merged result"))
    assert result == "merged result"


def test_merge_learnings_fallback_on_llm_error() -> None:
    """LLM raises — returns concatenation fallback, does not raise."""

    class RaiseMock:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM error")

    result = merge_learnings("old", "new", RaiseMock())
    assert result == "old\nnew"

"""Tests for assemble_context. Must pass without tiktoken installed."""

import pytest

from agent.memory.config import MemoryConfig
from agent.memory.context import assemble_context
from agent.memory.models import Personality, Project, SessionDigest
from agent.memory.tokens import count_tokens


def test_returns_empty_when_all_none() -> None:
    """Returns empty string when all inputs are None."""
    result = assemble_context(None, None, None, MemoryConfig())
    assert result == ""


def test_personality_always_included_full() -> None:
    """Personality (soul, immutable_core) is always included in full."""
    personality = Personality(soul="be kind", immutable_core="never lie")
    config = MemoryConfig()
    result = assemble_context(personality, None, None, config)
    assert "be kind" in result
    assert "never lie" in result
    assert "## Core Identity" in result
    assert "## Soul" in result


def test_full_assembly_within_budget() -> None:
    """All three sections appear when within budget."""
    personality = Personality(
        soul="I am helpful.",
        immutable_core="Never lie.",
    )
    project = Project(
        project_id="p1",
        description="Test",
        status="active",
        learnings="We built a CLI. Key learnings: use argparse, add tests.",
    )
    digest = SessionDigest(
        session_id="s1",
        project_id="p1",
        timestamp="2025-01-01T12:00:00Z",
        summary="User asked for help with Python.",
        capabilities=["read_file"],
        learnings="User prefers verbose output.",
    )
    config = MemoryConfig(context_token_budget=4000)
    result = assemble_context(personality, project, digest, config)
    assert "## Core Identity" in result
    assert "## Soul" in result
    assert "## Previous Session" in result
    assert "User asked for help with Python" in result
    assert "## Project Context" in result
    assert "We built a CLI" in result


def test_digest_dropped_when_doesnt_fit() -> None:
    """Digest is skipped when it doesn't fit in remaining budget."""
    # Personality ~50 tokens (38 words), budget 200, remaining ~150
    soul = " ".join(["word"] * 38)
    personality = Personality(soul=soul, immutable_core="Core values here.")
    # Digest ~200 tokens (154 words) — won't fit in remaining 150
    digest_summary = " ".join(["summary_word"] * 154)
    digest = SessionDigest(
        session_id="s1",
        project_id="p1",
        timestamp="2025-01-01T12:00:00Z",
        summary=digest_summary,
        capabilities=[],
        learnings="",
    )
    config = MemoryConfig(context_token_budget=200)
    result = assemble_context(personality, None, digest, config)
    # Digest should be dropped (output should not contain the digest summary)
    assert digest_summary not in result
    assert "## Previous Session" not in result


def test_learnings_truncated_to_fit() -> None:
    """Project learnings truncated to fit remaining budget."""
    # Personality ~20 tokens (~15 words)
    personality = Personality(
        soul="Be helpful.",
        immutable_core=" ".join(["core"] * 10),
    )
    # Learnings ~500+ tokens
    learnings = " ".join(["learning"] * 400)
    project = Project(
        project_id="p1",
        description="Test",
        status="active",
        learnings=learnings,
    )
    config = MemoryConfig(context_token_budget=100, learnings_max_tokens=80)
    result = assemble_context(personality, project, None, config)
    # Result should fit within soft ceiling (~120 tokens including headers)
    assert count_tokens(result) <= 120
    assert "## Project Context" in result


def test_soul_never_truncated_even_over_budget() -> None:
    """Soul is always included in full, even when over budget."""
    # Soul ~100 tokens (77 words), budget only 10
    soul = " ".join(["soul_word"] * 77)
    personality = Personality(soul=soul, immutable_core="Core.")
    config = MemoryConfig(context_token_budget=10)
    result = assemble_context(personality, None, None, config)
    # Soul must be fully present
    assert soul in result
    assert "soul_word" in result


def test_empty_learnings_no_project_context_section() -> None:
    """Empty project learnings produces no Project Context section."""
    project = Project(
        project_id="p1",
        description="Test",
        status="active",
        learnings="",
    )
    personality = Personality(soul="Hi", immutable_core="Core")
    config = MemoryConfig()
    result = assemble_context(personality, project, None, config)
    assert "## Project Context" not in result
    assert "## Core Identity" in result


def test_no_project_context_contains_only_personality() -> None:
    """With no project/digest, output contains only personality sections."""
    personality = Personality(soul="be kind", immutable_core="never lie")
    config = MemoryConfig()
    result = assemble_context(personality, None, None, config)
    assert "## Core Identity" in result
    assert "## Soul" in result
    assert "## Previous Session" not in result
    assert "## Project Context" not in result

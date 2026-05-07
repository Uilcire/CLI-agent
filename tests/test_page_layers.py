"""Tests for the two-layer page utilities."""

from __future__ import annotations

import pytest

from agent.assistant_memory.page import (
    TIMELINE_SEPARATOR,
    append_timeline,
    format_sourced_bullet,
    join_layers,
    rewrite_compiled,
    split_layers,
)


def test_split_no_separator_returns_all_compiled():
    body = "# Title\n\nSome state\n"
    compiled, timeline = split_layers(body)
    assert "Some state" in compiled
    assert timeline == ""


def test_split_join_roundtrip_preserves_both_layers():
    compiled = "# Alex\n\n## State\n- engineer at Anthropic"
    timeline = "## Timeline\n- **2026-05-07** | session — first mention"
    joined = join_layers(compiled, timeline)
    c2, t2 = split_layers(joined)
    assert c2.strip() == compiled.strip()
    assert "first mention" in t2
    assert t2.lstrip().startswith("## Timeline")


def test_join_emits_exactly_one_separator():
    body = join_layers("# X", "## Timeline\n- **2026-05-07** | session — hi")
    assert body.count("---\n\n## Timeline") == 1
    assert TIMELINE_SEPARATOR.strip() in body


def test_append_timeline_creates_section_on_empty_page():
    body = "# Alex\n\n## State\n- (none)\n"
    out = append_timeline(body, "2026-05-07", "session", "first mention")
    assert "## Timeline" in out
    assert "- **2026-05-07** | session — first mention" in out
    # Compiled truth preserved.
    compiled, timeline = split_layers(out)
    assert "## State" in compiled
    assert "first mention" in timeline


def test_append_timeline_appends_to_existing_section():
    body = (
        "# Alex\n\n## State\n- engineer\n\n---\n\n"
        "## Timeline\n- **2026-04-01** | session — old entry\n"
    )
    out = append_timeline(body, "2026-05-07", "user", "moved jobs")
    _, timeline = split_layers(out)
    assert "old entry" in timeline
    assert "moved jobs" in timeline
    assert timeline.index("old entry") < timeline.index("moved jobs")


def test_rewrite_compiled_preserves_timeline():
    body = (
        "# Old\n\nold state\n\n---\n\n"
        "## Timeline\n- **2026-04-01** | session — entry one\n"
        "- **2026-04-15** | session — entry two\n"
    )
    out = rewrite_compiled(body, "# New\n\n## State\n- new state")
    compiled, timeline = split_layers(out)
    assert "new state" in compiled
    assert "old state" not in compiled
    assert "entry one" in timeline
    assert "entry two" in timeline


def test_format_sourced_bullet_observed_minimal():
    bullet = format_sourced_bullet("likes oat milk", "observed")
    assert bullet.startswith("- likes oat milk")
    assert "_[observed]_" in bullet


def test_format_sourced_bullet_inferred_includes_confidence():
    bullet = format_sourced_bullet(
        "probably introvert", "inferred", confidence="medium"
    )
    assert "_[inferred, confidence: medium]_" in bullet


def test_format_sourced_bullet_self_described_with_date():
    bullet = format_sourced_bullet(
        "I am a backend engineer", "self-described", date="2026-05-07"
    )
    assert "self-described" in bullet
    assert "2026-05-07" in bullet


def test_format_sourced_bullet_rejects_bad_source_type():
    with pytest.raises(ValueError):
        format_sourced_bullet("x", "guessed")


def test_format_sourced_bullet_rejects_inferred_without_confidence():
    with pytest.raises(ValueError):
        format_sourced_bullet("x", "inferred")


def test_format_sourced_bullet_rejects_bad_confidence():
    with pytest.raises(ValueError):
        format_sourced_bullet("x", "inferred", confidence="maybe")

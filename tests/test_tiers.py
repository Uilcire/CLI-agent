"""Tests for the tier-based people-page module (Phase D)."""

from __future__ import annotations

import pytest

from agent.assistant_memory.store import AssistantMemoryStore
from agent.assistant_memory.tiers import (
    TIER_1_RELATIONS,
    compute_tier,
    format_people_manifest_line,
    people_slug_from_path,
    record_mention,
    should_write_compiled,
    update_people_manifest_line,
)


# ---- compute_tier truth table -----------------------------------------


@pytest.mark.parametrize(
    "count,relation,expected",
    [
        # count 0
        (0, "", 3),
        (0, "mom", 1),
        (0, "colleague", 2),
        # count 3 — promotes to tier 2 (relation empty) or tier 1 (mom)
        (3, "", 2),
        (3, "mom", 1),
        (3, "colleague", 2),
        # count 8 — always tier 1
        (8, "", 1),
        (8, "mom", 1),
        (8, "colleague", 1),
        # boundaries
        (2, "", 3),
        (7, "", 2),
        (7, "colleague", 2),
    ],
)
def test_compute_tier_truth_table(count: int, relation: str, expected: int) -> None:
    assert compute_tier(count, relation) == expected


def test_tier_1_relations_set_contents() -> None:
    assert "mom" in TIER_1_RELATIONS
    assert "best-friend" in TIER_1_RELATIONS
    assert "colleague" not in TIER_1_RELATIONS


# ---- record_mention behavior ------------------------------------------


def test_record_mention_creates_stub(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = record_mention(store, "alice", "2026-05-07")

    assert meta["mention_count"] == 1
    assert meta["tier"] == 3
    assert meta["first_seen"] == "2026-05-07"
    assert meta["last_mentioned"] == "2026-05-07"
    assert meta["relation"] == ""
    assert meta["aliases"] == []

    on_disk_meta, body = store.read_file("people/alice.md")
    assert on_disk_meta["mention_count"] == 1
    assert "[stub" in body
    assert "## Timeline" in body
    assert body.startswith("# alice")


def test_record_mention_bumps_count_and_promotes(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    record_mention(store, "bob", "2026-05-01")
    record_mention(store, "bob", "2026-05-02")
    meta = record_mention(store, "bob", "2026-05-03")

    # Third mention -> tier 2.
    assert meta["mention_count"] == 3
    assert meta["tier"] == 2
    assert meta["first_seen"] == "2026-05-01"
    assert meta["last_mentioned"] == "2026-05-03"


def test_record_mention_promotes_tier2_to_tier1_at_eighth(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    for i in range(1, 8):
        meta = record_mention(store, "carol", f"2026-05-{i:02d}")
    # After 7 mentions, still tier 2.
    assert meta["mention_count"] == 7
    assert meta["tier"] == 2

    meta = record_mention(store, "carol", "2026-05-08")
    assert meta["mention_count"] == 8
    assert meta["tier"] == 1


def test_record_mention_relation_mom_promotes_to_tier1_immediately(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = record_mention(store, "mama", "2026-05-07", relation="mom")

    assert meta["mention_count"] == 1
    assert meta["relation"] == "mom"
    assert meta["tier"] == 1


def test_record_mention_relation_colleague_promotes_to_tier2(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = record_mention(store, "dave", "2026-05-07", relation="colleague")

    assert meta["mention_count"] == 1
    assert meta["relation"] == "colleague"
    assert meta["tier"] == 2


def test_record_mention_relation_normalized_to_lower(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = record_mention(store, "ed", "2026-05-07", relation="MOM")
    assert meta["relation"] == "mom"
    assert meta["tier"] == 1


def test_record_mention_preserves_existing_body(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    record_mention(store, "frank", "2026-05-01")
    # Manually rewrite body — record_mention must not clobber it.
    meta, body = store.read_file("people/frank.md")
    store.write_file("people/frank.md", meta, body + "\n- **2026-05-01** | session — hi\n")

    meta2 = record_mention(store, "frank", "2026-05-02")
    _, body2 = store.read_file("people/frank.md")
    assert "session — hi" in body2
    assert meta2["mention_count"] == 2


def test_record_mention_rejects_empty_slug(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    with pytest.raises(ValueError):
        record_mention(store, "", "2026-05-07")


# ---- manifest line ----------------------------------------------------


def test_format_people_manifest_line_basic() -> None:
    meta = {
        "tier": 1,
        "relation": "colleague",
        "mention_count": 12,
        "last_mentioned": "2026-05-01",
        "aliases": ["alice-johnson", "AJ"],
    }
    line = format_people_manifest_line("alice", meta)
    assert line.startswith("- **alice.md**")
    assert "tier:1" in line
    assert "relation:colleague" in line
    assert "mentions:12" in line
    assert "last:2026-05-01" in line
    assert "aliases: alice-johnson, AJ" in line


def test_update_people_manifest_line_appends_then_replaces(tmp_path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = record_mention(store, "gina", "2026-05-07", relation="colleague")
    update_people_manifest_line(store, "gina", meta)
    manifest = store.read_manifest("people")
    assert "**gina.md**" in manifest
    assert "tier:2" in manifest

    # Bump again -> still one line for gina.
    meta = record_mention(store, "gina", "2026-05-08")
    update_people_manifest_line(store, "gina", meta)
    manifest = store.read_manifest("people")
    assert manifest.count("**gina.md**") == 1
    assert "mentions:2" in manifest


# ---- helpers ----------------------------------------------------------


def test_people_slug_from_path() -> None:
    assert people_slug_from_path("people/alice.md") == "alice"
    assert people_slug_from_path("people/jane-doe.md") == "jane-doe"
    assert people_slug_from_path("preferences/coffee.md") is None
    assert people_slug_from_path("people/sub/alice.md") is None
    assert people_slug_from_path("") is None


def test_should_write_compiled() -> None:
    assert should_write_compiled({"tier": 1}) is True
    assert should_write_compiled({"tier": 2}) is True
    assert should_write_compiled({"tier": 3}) is False
    assert should_write_compiled({}) is False  # default tier 3
    assert should_write_compiled({"tier": "bogus"}) is False

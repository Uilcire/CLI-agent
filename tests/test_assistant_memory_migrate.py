"""Tests for the JSON -> markdown assistant memory migration script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.assistant_memory.schema import parse_frontmatter
from scripts.migrate_to_assistant_memory import main, migrate


def _build_old_memory(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir()
    (root / "digests").mkdir()
    (root / "sessions").mkdir()

    (root / "personality.json").write_text(
        json.dumps(
            {
                "soul": "I am a careful agent.",
                "immutable_core": "Be honest. Be helpful.",
            }
        )
    )

    proj_a = {
        "project_id": "alpha",
        "description": "Alpha project",
        "status": "active",
        "tags": ["python"],
        "capabilities": ["read_file", "write_file"],
        "sessions": [],
        "learnings": "Learned about atomic writes.",
        "last_summarized_session": None,
        "cwd": "/tmp/alpha",
    }
    proj_b = {
        "project_id": "beta",
        "description": "Beta project",
        "status": "paused",
        "tags": [],
        "capabilities": [],
        "sessions": [],
        "learnings": "",
        "last_summarized_session": None,
        "cwd": "",
    }
    (root / "projects" / "alpha.json").write_text(json.dumps(proj_a))
    (root / "projects" / "beta.json").write_text(json.dumps(proj_b))

    digests = [
        {
            "session_id": "s1",
            "project_id": "alpha",
            "timestamp": "2026-03-15T10:00:00",
            "summary": "Worked on tool registry.",
            "capabilities": ["read_file"],
            "learnings": "Registry pattern useful.",
            "fictional_backstory": "",
        },
        {
            "session_id": "s2",
            "project_id": "alpha",
            "timestamp": "2026-03-16T14:30:00",
            "summary": "Refactored compaction.",
            "capabilities": [],
            "learnings": "",
            "fictional_backstory": "Once upon a time...",
        },
        {
            "session_id": "s3",
            "project_id": "beta",
            "timestamp": "2026-04-02T09:00:00",
            "summary": "Started beta scaffold.",
            "capabilities": ["bash"],
            "learnings": "Beta needs more thought.",
            "fictional_backstory": "",
        },
    ]
    for d in digests:
        (root / "digests" / f"{d['session_id']}.json").write_text(json.dumps(d))


def test_migration_writes_expected_layout(tmp_path: Path) -> None:
    src = tmp_path / "old"
    dst = tmp_path / "new"
    _build_old_memory(src)

    summary = migrate(src, dst, dry_run=False, archive=False, force=False)

    assert summary.personality_migrated is True
    assert sorted(summary.projects) == ["alpha", "beta"]
    assert summary.digests == 3

    agent_meta, agent_body = parse_frontmatter((dst / "identity" / "agent.md").read_text())
    assert agent_meta["name"] == "agent"
    assert agent_meta["type"] == "identity"
    assert agent_meta["immutable_core"] == "Be honest. Be helpful."
    assert "I am a careful agent." in agent_body

    for pid in ("alpha", "beta"):
        proj_path = dst / "projects" / f"{pid}.md"
        assert proj_path.exists()
        meta, body = parse_frontmatter(proj_path.read_text())
        assert meta["project_id"] == pid
        assert "## Description" in body
        assert "## Capabilities" in body
        assert "## Learnings" in body

    march = dst / "log" / "2026-03" / "2026-03-15.md"
    march2 = dst / "log" / "2026-03" / "2026-03-16.md"
    april = dst / "log" / "2026-04" / "2026-04-02.md"
    assert march.exists() and march2.exists() and april.exists()
    assert "Session s1 (alpha)" in march.read_text()
    assert "Worked on tool registry." in march.read_text()
    assert "Once upon a time..." in march2.read_text()
    assert "Started beta scaffold." in april.read_text()

    manifest = (dst / "projects" / "_manifest.md").read_text()
    assert "alpha.md" in manifest
    assert "beta.md" in manifest

    assert (dst / "identity" / "me.md").exists()
    assert (dst / "context" / "current.md").exists()
    assert (dst / "_index.md").exists()
    assert (dst / "people" / "_manifest.md").exists()
    assert (dst / "preferences" / "_manifest.md").exists()
    assert (dst / "log" / "_manifest.md").exists()


def test_archive_renames_src(tmp_path: Path) -> None:
    src = tmp_path / "old"
    dst = tmp_path / "new"
    _build_old_memory(src)

    summary = migrate(src, dst, dry_run=False, archive=True, force=False)

    assert not src.exists()
    legacy = Path(f"{src}.legacy")
    assert legacy.exists()
    assert summary.archived_to == str(legacy)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "old"
    dst = tmp_path / "new"
    _build_old_memory(src)

    summary = migrate(src, dst, dry_run=True, archive=True, force=False)

    assert summary.personality_migrated is True
    assert sorted(summary.projects) == ["alpha", "beta"]
    assert summary.digests == 3
    assert not dst.exists()
    assert src.exists()
    assert not Path(f"{src}.legacy").exists()


def test_refuses_existing_dst_without_force(tmp_path: Path) -> None:
    src = tmp_path / "old"
    dst = tmp_path / "new"
    _build_old_memory(src)
    dst.mkdir()
    (dst / "stale.md").write_text("hi")

    with pytest.raises(RuntimeError, match="already has files"):
        migrate(src, dst, dry_run=False, archive=False, force=False)


def test_cli_main_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "migrate" in out.lower()

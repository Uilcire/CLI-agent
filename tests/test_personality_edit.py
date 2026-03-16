"""Tests for personality_edit tool and str_replace blocking personality.json."""

import json

from agent.tools.registry import execute


def test_personality_edit_creates_file_when_missing(tmp_path):
    """When personality.json does not exist, creates it with updates."""
    path = tmp_path / "agent-memory" / "personality.json"
    path.parent.mkdir(parents=True)

    result = execute(
        "personality_edit",
        {"updates": {"soul": "Test soul."}, "path": str(path)},
    )

    assert "Updated personality.json" in result
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["soul"] == "Test soul."


def test_personality_edit_rejects_immutable_core(tmp_path):
    """immutable_core cannot be edited via personality_edit."""
    path = tmp_path / "personality.json"
    path.write_text(
        json.dumps({"soul": "Soul.", "immutable_core": "Original core."}, indent=2),
        encoding="utf-8",
    )

    result = execute(
        "personality_edit",
        {"updates": {"immutable_core": "Hacked core."}, "path": str(path)},
    )

    assert "Error" in result
    assert "immutable_core" in result
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["immutable_core"] == "Original core."


def test_personality_edit_merges_into_existing(tmp_path):
    """Merges updates into existing personality.json without overwriting other keys."""
    path = tmp_path / "personality.json"
    path.write_text(
        json.dumps({"soul": "Original soul.", "immutable_core": "Original core."}, indent=2),
        encoding="utf-8",
    )

    result = execute(
        "personality_edit",
        {"updates": {"soul": "New soul."}, "path": str(path)},
    )

    assert "Updated personality.json" in result
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["soul"] == "New soul."
    assert data["immutable_core"] == "Original core."


def test_personality_edit_empty_updates_returns_error(tmp_path):
    """Empty updates returns an error."""
    path = tmp_path / "personality.json"
    path.write_text("{}", encoding="utf-8")

    result = execute("personality_edit", {"updates": {}, "path": str(path)})

    assert "Error" in result


def test_personality_edit_rejects_soul_over_300_chars(tmp_path):
    """soul over 300 chars is rejected with feedback to summarize."""
    path = tmp_path / "personality.json"
    path.write_text(
        json.dumps({"soul": "Short.", "immutable_core": "Core."}, indent=2),
        encoding="utf-8",
    )

    long_soul = "x" * 350
    result = execute(
        "personality_edit",
        {"updates": {"soul": long_soul}, "path": str(path)},
    )

    assert "Error" in result
    assert "350" in result
    assert "300" in result
    assert "summarize" in result.lower()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["soul"] == "Short."


def test_str_replace_blocks_personality_json(tmp_path, monkeypatch):
    """str_replace cannot edit personality.json; must use personality_edit tool."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agent-memory").mkdir(parents=True)
    path = tmp_path / "agent-memory" / "personality.json"
    path.write_text('{"soul": "original"}', encoding="utf-8")

    result = execute(
        "str_replace",
        {"path": "agent-memory/personality.json", "old_str": "original", "new_str": "hacked"},
    )

    assert "personality.json cannot be edited with str_replace" in result
    assert "personality_edit" in result
    assert path.read_text(encoding="utf-8") == '{"soul": "original"}'


def test_personality_edit_uses_default_path(tmp_path, monkeypatch):
    """When path omitted, uses default agent-memory/personality.json (relative to cwd)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agent-memory").mkdir(parents=True)

    result = execute("personality_edit", {"updates": {"soul": "Minimal test."}})

    assert "Updated personality.json" in result
    data = json.loads((tmp_path / "agent-memory" / "personality.json").read_text(encoding="utf-8"))
    assert data["soul"] == "Minimal test."

"""Tests for the assistant memory store foundation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.assistant_memory.schema import dump_frontmatter, parse_frontmatter
from agent.assistant_memory.store import AssistantMemoryStore


def test_frontmatter_roundtrip() -> None:
    meta = {
        "name": "alex",
        "type": "person",
        "tags": ["girlfriend", "sf"],
        "since": 2024,
    }
    body = "# Alex\n\nSome notes about Alex.\n"
    text = dump_frontmatter(meta, body)
    parsed_meta, parsed_body = parse_frontmatter(text)
    assert parsed_meta == meta
    assert parsed_body == body


def test_parse_frontmatter_no_meta() -> None:
    body = "# Just a body\n\nno frontmatter here\n"
    meta, parsed_body = parse_frontmatter(body)
    assert meta == {}
    assert parsed_body == body


def test_atomic_write_creates_file_with_meta_and_body(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    meta = {"name": "alex", "relation": "girlfriend"}
    body = "# Alex\n\nbody text\n"
    store.write_file("people/alex.md", meta, body)

    file_path = tmp_path / "people" / "alex.md"
    assert file_path.exists()
    assert not (tmp_path / "people" / "alex.md.tmp").exists()

    raw = file_path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    assert "name: alex" in raw
    assert "# Alex" in raw

    read_meta, read_body = store.read_file("people/alex.md")
    assert read_meta == meta
    assert read_body == body


def test_list_files_excludes_manifest(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    store.write_file("people/alex.md", {"name": "alex"}, "body\n")
    store.write_file("people/mom.md", {"name": "mom"}, "body\n")
    store.write_manifest("people", "# People Manifest\n- alex.md\n- mom.md\n")

    files = store.list_files("people")
    assert "people/alex.md" in files
    assert "people/mom.md" in files
    assert all("_manifest.md" not in f for f in files)
    assert len(files) == 2


def test_read_immutable_core(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    immutable = "Be honest. Never deceive the user.\nProtect their privacy.\n"
    store.write_file(
        "identity/agent.md",
        {"immutable_core": immutable, "version": 1},
        "# Agent Soul\n\nMutable body.\n",
    )

    assert store.read_immutable_core() == immutable
    assert "Mutable body" in store.read_agent_soul()


def test_read_immutable_core_missing(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    assert store.read_immutable_core() == ""
    assert store.read_agent_soul() == ""


def test_read_current_context_missing(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    assert store.read_current_context() == ""


def test_store_creates_scope_dirs(tmp_path: Path) -> None:
    AssistantMemoryStore(tmp_path)
    for scope in ("identity", "people", "preferences", "projects", "context", "log"):
        assert (tmp_path / scope).is_dir()


# ---- path-safety --------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "../etc/passwd",
        "people/../../etc/passwd",
        "/etc/passwd",
        "\\windows\\system32",
        "people/\x00alex.md",
        "",
        "..",
    ],
)
def test_safe_rel_rejects_unsafe_paths(tmp_path: Path, rel: str) -> None:
    store = AssistantMemoryStore(tmp_path)
    with pytest.raises(ValueError):
        store._safe_rel(rel)


def test_read_file_rejects_traversal(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    with pytest.raises(ValueError):
        store.read_file("../../etc/passwd")
    with pytest.raises(ValueError):
        store.write_file("/etc/evil.md", {}, "x")


def test_tmp_files_swept_on_init(tmp_path: Path) -> None:
    # First create the scope tree, then drop a bogus tmp leftover.
    AssistantMemoryStore(tmp_path)
    leftover = tmp_path / "people" / "alex.md.tmp"
    leftover.write_text("garbage", encoding="utf-8")
    assert leftover.exists()
    AssistantMemoryStore(tmp_path)
    assert not leftover.exists()


def test_parse_frontmatter_preserves_block_scalar_with_dashes() -> None:
    """A `|` block scalar containing `---` must not break parse."""
    text = (
        "---\n"
        "name: agent\n"
        "immutable_core: |\n"
        "  Be honest.\n"
        "  ---\n"
        "  Protect the user.\n"
        "version: 1\n"
        "---\n"
        "\n"
        "# Body\n"
    )
    meta, body = parse_frontmatter(text)
    assert meta.get("name") == "agent"
    assert meta.get("version") == 1
    assert "Be honest." in meta["immutable_core"]
    assert "Protect the user." in meta["immutable_core"]
    assert "---" in meta["immutable_core"]
    assert "# Body" in body


def test_parse_frontmatter_malformed_yaml_returns_body(tmp_path: Path) -> None:
    text = "---\nfoo: [unbalanced\n---\n\nbody\n"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert "body" in body

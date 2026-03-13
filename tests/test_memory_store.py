"""Tests for LocalMemoryStore."""

from pathlib import Path

import pytest

from agent.memory.models import ActiveSession, Personality, Project, SessionDigest
from agent.memory.store import LocalMemoryStore


def test_constructor_creates_directories(tmp_path: Path) -> None:
    """Constructor creates projects/, digests/, sessions/ subdirs."""
    data_dir = tmp_path / "mem"
    store = LocalMemoryStore(str(data_dir))
    assert (data_dir / "projects").is_dir()
    assert (data_dir / "digests").is_dir()
    assert (data_dir / "sessions").is_dir()


def test_personality_roundtrip(tmp_path: Path) -> None:
    """Save, load, assert equal; load before any save returns None."""
    store = LocalMemoryStore(str(tmp_path))
    assert store.get_personality() is None

    p = Personality(soul="helpful", immutable_core="honest")
    store.save_personality(p)
    loaded = store.get_personality()
    assert loaded is not None
    assert loaded == p


def test_project_roundtrip(tmp_path: Path) -> None:
    """Save, load by ID, assert equal; unknown ID returns None."""
    store = LocalMemoryStore(str(tmp_path))
    proj = Project(project_id="abc", description="Test", status="active")
    store.save_project(proj)
    loaded = store.get_project("abc")
    assert loaded is not None
    assert loaded == proj
    assert store.get_project("unknown") is None


def test_list_projects(tmp_path: Path) -> None:
    """Save 3 projects, assert len(list_projects()) == 3."""
    store = LocalMemoryStore(str(tmp_path))
    for i, pid in enumerate(["c", "a", "b"]):
        store.save_project(Project(project_id=pid, description=f"Project {i}", status="active"))
    projs = store.list_projects()
    assert len(projs) == 3
    assert [p.project_id for p in projs] == ["a", "b", "c"]


def test_digest_roundtrip(tmp_path: Path) -> None:
    """Save digest for project A, list_digests('A') returns it; list_digests('B') empty."""
    store = LocalMemoryStore(str(tmp_path))
    d = SessionDigest(session_id="s1", project_id="A", timestamp="2025-01-01T00:00:00", summary="Done")
    store.save_digest(d)
    assert store.list_digests("A") == [d]
    assert store.list_digests("B") == []


def test_list_digests_filter(tmp_path: Path) -> None:
    """Save 3 digests for project A, 2 for B; assert counts correct."""
    store = LocalMemoryStore(str(tmp_path))
    for i in range(3):
        store.save_digest(
            SessionDigest(
                session_id=f"sA{i}",
                project_id="A",
                timestamp=f"2025-01-01T{i:02d}:00:00",
                summary="",
            )
        )
    for i in range(2):
        store.save_digest(
            SessionDigest(
                session_id=f"sB{i}",
                project_id="B",
                timestamp=f"2025-01-01T{i:02d}:00:00",
                summary="",
            )
        )
    assert len(store.list_digests("A")) == 3
    assert len(store.list_digests("B")) == 2


def test_active_session_lifecycle(tmp_path: Path) -> None:
    """Save, load, delete, load returns None; list_active_sessions empty after delete."""
    store = LocalMemoryStore(str(tmp_path))
    s = ActiveSession(session_id="s1", project_id="p1", messages=[])
    store.save_active_session(s)
    loaded = store.load_active_session("s1")
    assert loaded is not None
    assert loaded == s

    store.delete_active_session("s1")
    assert store.load_active_session("s1") is None
    assert store.list_active_sessions() == []


def test_atomic_write_integrity(tmp_path: Path) -> None:
    """Save project, save again with different description, load returns updated."""
    store = LocalMemoryStore(str(tmp_path))
    p1 = Project(project_id="x", description="First", status="active")
    store.save_project(p1)
    p2 = Project(project_id="x", description="Second", status="active")
    store.save_project(p2)
    loaded = store.get_project("x")
    assert loaded is not None
    assert loaded.description == "Second"


def test_tmp_files_ignored(tmp_path: Path) -> None:
    """Manually create projects/foo.tmp, assert list_projects() does not include it."""
    store = LocalMemoryStore(str(tmp_path))
    (tmp_path / "projects" / "foo.tmp").write_text("{}")
    store.save_project(Project(project_id="real", description="Real", status="active"))
    projs = store.list_projects()
    assert len(projs) == 1
    assert projs[0].project_id == "real"

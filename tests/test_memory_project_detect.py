"""Tests for project detection: cwd_project_id, scan_cwd, _find_similar, detect_and_onboard, onboard_project."""

import os

import pytest

from agent.memory.llm import MockLLMClient
from agent.memory.models import Project
from agent.memory.onboarding import (
    _find_similar,
    cwd_project_id,
    detect_and_onboard,
    onboard_project,
    scan_cwd,
)
from agent.memory.store import LocalMemoryStore


def test_cwd_project_id_stable() -> None:
    """Same path yields same ID; trailing slash normalized; different paths yield different IDs."""
    a = cwd_project_id("/some/path")
    b = cwd_project_id("/some/path")
    assert a == b
    c = cwd_project_id("/some/path/")
    assert a == c
    d = cwd_project_id("/other/path")
    assert a != d


def test_cwd_project_id_length() -> None:
    """Project ID is 12 characters."""
    assert len(cwd_project_id("/any/path")) == 12


def test_scan_cwd_returns_dir_name(tmp_path: pytest.TempPathFactory) -> None:
    """scan_cwd returns dir_name as basename of path."""
    result = scan_cwd(str(tmp_path))
    assert result["dir_name"] == tmp_path.name


def test_scan_cwd_file_listing(tmp_path: pytest.TempPathFactory) -> None:
    """Visible files appear; hidden files excluded."""
    (tmp_path / "foo.py").touch()
    (tmp_path / "bar.txt").touch()
    (tmp_path / ".hidden").touch()
    result = scan_cwd(str(tmp_path))
    assert "foo.py" in result["file_listing"]
    assert "bar.txt" in result["file_listing"]
    assert ".hidden" not in result["file_listing"]


def test_scan_cwd_readme_found(tmp_path: pytest.TempPathFactory) -> None:
    """README content truncated to 500 chars."""
    content = "This is a test project. " * 50
    (tmp_path / "README.md").write_text(content)
    result = scan_cwd(str(tmp_path))
    assert result["readme_snippet"].startswith("This is a test project.")
    assert len(result["readme_snippet"]) <= 500


def test_scan_cwd_no_readme(tmp_path: pytest.TempPathFactory) -> None:
    """Empty dir has no README."""
    result = scan_cwd(str(tmp_path))
    assert result["readme_snippet"] == "No README found."


def test_find_similar_tag_overlap() -> None:
    """Tag overlap returns only matching project."""
    proj1 = Project(
        project_id="1",
        description="Python CLI",
        status="active",
        tags=["python", "cli"],
    )
    proj2 = Project(
        project_id="2",
        description="Ruby web",
        status="active",
        tags=["ruby", "web"],
    )
    result = _find_similar(["python", "testing"], [proj1, proj2])
    assert result == [proj1]


def test_find_similar_empty_tags() -> None:
    """Empty new_tags returns no matches."""
    proj1 = Project(project_id="1", description="x", status="active", tags=["python"])
    proj2 = Project(project_id="2", description="y", status="active", tags=["ruby"])
    assert _find_similar([], [proj1, proj2]) == []


def test_detect_and_onboard_creates_project(tmp_path: pytest.TempPathFactory) -> None:
    """Valid LLM response creates project with correct fields."""
    store = LocalMemoryStore(str(tmp_path))
    response = '{"description": "A Python CLI tool.", "suggested_tags": ["python", "cli"], "suggested_capabilities": ["click"]}'
    llm = MockLLMClient(response)
    project = detect_and_onboard(str(tmp_path), store, llm, print_fn=lambda *a: None)
    assert project.description == "A Python CLI tool."
    assert project.tags == ["python", "cli"]
    assert project.cwd == os.path.abspath(str(tmp_path))
    assert project.project_id == cwd_project_id(str(tmp_path))
    assert store.get_project(project.project_id) is not None


def test_detect_and_onboard_seeds_from_similar(tmp_path: pytest.TempPathFactory) -> None:
    """Capabilities seeded from similar projects."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(
            project_id="abc123",
            description="Python CLI",
            status="active",
            tags=["python", "cli"],
            capabilities=["argparse", "rich"],
        )
    )
    (tmp_path / "main.py").touch()
    response = '{"description": "A CLI.", "suggested_tags": ["python", "cli"], "suggested_capabilities": ["click"]}'
    llm = MockLLMClient(response)
    project = detect_and_onboard(str(tmp_path), store, llm, print_fn=lambda *a: None)
    assert "click" in project.capabilities
    assert "argparse" in project.capabilities
    assert "rich" in project.capabilities


def test_detect_and_onboard_llm_failure_fallback(tmp_path: pytest.TempPathFactory) -> None:
    """LLM failure yields fallback project with dir name."""
    store = LocalMemoryStore(str(tmp_path))
    llm = MockLLMClient("not json")
    project = detect_and_onboard(str(tmp_path), store, llm, print_fn=lambda *a: None)
    assert project.description is not None
    assert tmp_path.name in project.description


def test_detect_and_onboard_prints_progress(tmp_path: pytest.TempPathFactory) -> None:
    """Progress messages printed."""
    store = LocalMemoryStore(str(tmp_path))
    llm = MockLLMClient('{"description": "x", "suggested_tags": [], "suggested_capabilities": []}')
    output = []
    detect_and_onboard(
        str(tmp_path),
        store,
        llm,
        print_fn=lambda *a: output.append(" ".join(str(x) for x in a)),
    )
    joined = " ".join(output)
    assert "Scanning" in joined
    assert "Classifying" in joined
    assert "Creating project" in joined


def test_onboard_project_uses_tag_overlap(tmp_path: pytest.TempPathFactory) -> None:
    """Capabilities from similar projects (tag overlap) are seeded into the new project."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(
            project_id="py1",
            description="Python web app",
            status="active",
            tags=["python", "web"],
            capabilities=["flask", "sqlalchemy"],
        )
    )
    # LLM returns tags that overlap with py1 → flask and sqlalchemy should be seeded
    llm = MockLLMClient('{"suggested_tags": ["python"], "relevant_capabilities": [], "rationale": "x"}')
    project = onboard_project("a python tool", store, llm, print_fn=lambda *a: None)
    assert "flask" in project.capabilities
    assert "sqlalchemy" in project.capabilities

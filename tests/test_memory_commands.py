"""Tests for /memory slash commands. No LLM calls."""

import pytest

from agent.config.settings import Settings
from agent.memory.manager import MemoryManager
from agent.memory.models import Project
from agent.memory.store import LocalMemoryStore

_TEST_SETTINGS = Settings(
    backend="openai",
    api_key="sk-test",
    model="gpt-4",
    max_tokens=100,
)


def _make_manager_with_project(tmp_path: pytest.TempPathFactory, project_id: str = "p1") -> MemoryManager:
    """Create MemoryManager with active session and a project."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(
            project_id=project_id,
            description="A test project",
            status="active",
            tags=["python", "test"],
            capabilities=["pytest"],
            sessions=["s1", "s2"],
            learnings="We use pytest for testing.",
        )
    )
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup(project_id=project_id)
    return manager


def test_handle_command_returns_none_for_non_command() -> None:
    """Non /memory input returns None."""
    from agent.memory.commands import handle_memory_command

    # We need a manager instance but won't use its store for these checks
    manager = MemoryManager(data_dir="/tmp/x", settings=_TEST_SETTINGS)

    assert handle_memory_command("hello world", manager) is None
    assert handle_memory_command("what is /memory", manager) is None


def test_memory_show_with_active_project(tmp_path: pytest.TempPathFactory) -> None:
    """handle_command /memory show displays project info."""
    memory = _make_manager_with_project(tmp_path)
    result = memory.handle_command("/memory show")

    assert result is not None
    assert "A test project" in result
    assert "python" in result
    assert "pytest" in result
    assert "2" in result


def test_memory_show_no_session(tmp_path: pytest.TempPathFactory) -> None:
    """Fresh manager without on_startup — /memory show returns string, contains 'none'."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    result = memory.handle_command("/memory show")

    assert result is not None
    assert "none" in result.lower() or "no active" in result.lower()


def test_memory_projects_empty(tmp_path: pytest.TempPathFactory) -> None:
    """Empty store — /memory projects returns 'No projects stored yet.'"""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()
    result = memory.handle_command("/memory projects")

    assert result == "No projects stored yet."


def test_memory_projects_lists_all(tmp_path: pytest.TempPathFactory) -> None:
    """Store has 2 projects — both appear in output."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(project_id="a", description="Project A", status="active")
    )
    store.save_project(
        Project(project_id="b", description="Project B", status="active")
    )
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()

    result = memory.handle_command("/memory projects")

    assert result is not None
    assert "Project A" in result
    assert "Project B" in result


def test_memory_clear_learnings(tmp_path: pytest.TempPathFactory) -> None:
    """clear learnings empties project.learnings and last_summarized_session."""
    memory = _make_manager_with_project(tmp_path)

    result = memory.handle_command("/memory clear learnings")

    assert result == "Project learnings cleared."
    project = memory._store.get_project("p1")
    assert project is not None
    assert project.learnings == ""
    assert project.last_summarized_session is None


def test_memory_clear_learnings_no_project(tmp_path: pytest.TempPathFactory) -> None:
    """Manager with no project_id — clear learnings returns 'No active project.'"""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()  # no project_id

    result = memory.handle_command("/memory clear learnings")

    assert result == "No active project."


def test_memory_help(tmp_path: pytest.TempPathFactory) -> None:
    """/memory help lists commands."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()

    result = memory.handle_command("/memory help")

    assert result is not None
    assert "/memory show" in result
    assert "/memory projects" in result


def test_memory_unknown_subcommand(tmp_path: pytest.TempPathFactory) -> None:
    """Unknown /memory subcommand returns message with 'Unknown'."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()

    result = memory.handle_command("/memory foobar")

    assert result is not None
    assert "Unknown" in result

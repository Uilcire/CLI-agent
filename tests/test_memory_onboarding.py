"""Tests for onboard_project. Use MockLLMClient and tmp_path."""

import pytest

from agent.memory.llm import MockLLMClient
from agent.memory.models import Project
from agent.memory.onboarding import onboard_project
from agent.memory.store import LocalMemoryStore


def test_onboard_first_project_ever(tmp_path: pytest.TempPathFactory) -> None:
    """Empty store, LLM returns tags/caps — project created and persisted."""
    store = LocalMemoryStore(str(tmp_path))
    llm = MockLLMClient(
        '{"suggested_tags": ["python", "cli"], "relevant_capabilities": [], "rationale": "New project."}'
    )
    project = onboard_project("Build a CLI tool", store, llm)

    assert project.tags == ["python", "cli"]
    assert project.capabilities == []
    assert project.status == "active"
    assert store.get_project(project.project_id) is not None


def test_onboard_with_similar_projects(tmp_path: pytest.TempPathFactory) -> None:
    """Pre-populate store with similar project — LLM suggests relevant capabilities."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(
            project_id="p1",
            description="Python web scraper",
            status="active",
            tags=["python", "scraping"],
            capabilities=["requests", "beautifulsoup"],
        )
    )
    llm = MockLLMClient(
        '{"suggested_tags": ["python", "scraping"], "relevant_capabilities": ["requests"], "rationale": "Similar scraping project."}'
    )
    project = onboard_project("Build a Python news scraper", store, llm)

    # LLM suggested "requests"; similar project also contributes "beautifulsoup"
    assert "requests" in project.capabilities
    assert "beautifulsoup" in project.capabilities


def test_onboard_llm_failure_still_creates_project(tmp_path: pytest.TempPathFactory) -> None:
    """LLM returns non-JSON — project created with empty tags/capabilities, no raise."""
    store = LocalMemoryStore(str(tmp_path))
    llm = MockLLMClient("not json")

    project = onboard_project("Some project", store, llm)

    assert project.tags == []
    assert project.capabilities == []
    assert project.project_id
    assert store.get_project(project.project_id) is not None


def test_onboard_project_id_is_unique(tmp_path: pytest.TempPathFactory) -> None:
    """Two onboard calls with same description — different project_ids."""
    store = LocalMemoryStore(str(tmp_path))
    llm = MockLLMClient(
        '{"suggested_tags": ["python"], "relevant_capabilities": [], "rationale": "x"}'
    )

    p1 = onboard_project("Same desc", store, llm)
    p2 = onboard_project("Same desc", store, llm)

    assert p1.project_id != p2.project_id


def test_onboard_similar_project_scoring(tmp_path: pytest.TempPathFactory) -> None:
    """Only Python project passed to LLM when onboarding Python ETL — Ruby excluded."""

    class CaptureMock:
        def __init__(self) -> None:
            self.last_user = ""

        def complete(self, system: str, user: str) -> str:
            self.last_user = user
            return '{"suggested_tags": [], "relevant_capabilities": [], "rationale": "x"}'

    store = LocalMemoryStore(str(tmp_path))
    store.save_project(
        Project(
            project_id="py1",
            description="Python data pipeline",
            status="active",
            tags=["python", "data"],
        )
    )
    store.save_project(
        Project(
            project_id="rb1",
            description="Ruby on Rails blog",
            status="active",
            tags=["ruby", "web"],
        )
    )
    mock = CaptureMock()
    onboard_project("Python ETL pipeline", store, mock)

    assert "Ruby" not in mock.last_user

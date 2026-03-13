"""Tests for SessionManager.end() (subprocess dispatch) and digest_worker.run_digest() (digest logic)."""

import pytest

from agent.config.settings import Settings
from agent.memory.config import MemoryConfig
from agent.memory.llm import MockLLMClient
from agent.memory.models import Project
from agent.memory.session import SessionManager
from agent.memory.store import LocalMemoryStore

_TEST_SETTINGS = Settings(
    backend="openai",
    api_key="sk-test",
    model="gpt-4",
    max_tokens=100,
)

DIGEST_JSON = '{"summary": "User asked about Python.", "capabilities": ["python"], "learnings": "User is a beginner."}'


# ---------------------------------------------------------------------------
# SessionManager.end() — dispatch behavior
# ---------------------------------------------------------------------------


def test_end_empty_session_returns_empty(tmp_path: pytest.TempPathFactory) -> None:
    """Empty session: end() returns 'empty', no digest, session deleted."""

    class RaiseIfCalled:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM should not be called for empty session")

    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=RaiseIfCalled())

    session = manager.start()
    result = manager.end(session)

    assert result.status == "empty"
    assert result.digest is None
    assert store.get_digest(session.session_id) is None
    assert store.load_active_session(session.session_id) is None


def test_end_nonempty_session_returns_background(tmp_path: pytest.TempPathFactory) -> None:
    """Non-empty session: end() returns 'background' immediately without doing digest work."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start()
    manager.record_turn(session, "user", "hello")

    result = manager.end(session)
    assert result.status == "background"
    assert result.digest is None


def test_end_leaves_session_on_disk_for_worker(tmp_path: pytest.TempPathFactory) -> None:
    """After end(), active session is still on disk for the worker to process."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start()
    manager.record_turn(session, "user", "hi")

    manager.end(session)
    # Session must still exist — the subprocess worker deletes it, not end()
    assert store.load_active_session(session.session_id) is not None


# ---------------------------------------------------------------------------
# digest_worker.run_digest() — full digest pipeline
# ---------------------------------------------------------------------------


def _make_run_digest(llm):
    """Return a run_digest callable that uses the given llm instead of RealLLMClient."""
    from agent.memory import digest_worker
    from agent.memory.digest import derive_digest, merge_learnings

    def _run(session_id: str, data_dir: str) -> None:
        from agent.memory.store import LocalMemoryStore as _Store

        store = _Store(data_dir)
        session = store.load_active_session(session_id)
        if session is None:
            return

        digest = derive_digest(session, llm)
        store.save_digest(digest)

        if session.project_id is not None:
            project = store.get_project(session.project_id)
            if project is not None:
                merged = merge_learnings(project.learnings, digest.learnings, llm)
                project.learnings = merged
                if session.session_id not in project.sessions:
                    project.sessions.append(session.session_id)
                store.save_project(project)

        store.delete_active_session(session_id)

    return _run


def test_run_digest_saves_digest(tmp_path: pytest.TempPathFactory) -> None:
    """run_digest saves digest to store and deletes active session."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    llm = MockLLMClient(DIGEST_JSON)
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=llm)

    session = manager.start()
    manager.record_turn(session, "user", "hello")
    manager.record_turn(session, "assistant", "hi there")
    manager.end(session)  # dispatches to worker, leaves session on disk

    run_digest = _make_run_digest(llm)
    run_digest(session.session_id, str(tmp_path))

    digest = store.get_digest(session.session_id)
    assert digest is not None
    assert digest.summary == "User asked about Python."
    assert digest.capabilities == ["python"]
    assert store.load_active_session(session.session_id) is None


def test_run_digest_updates_project_learnings(tmp_path: pytest.TempPathFactory) -> None:
    """run_digest merges digest learnings into project."""
    store = LocalMemoryStore(str(tmp_path))
    proj = Project(project_id="p1", description="Test", status="active", learnings="old")
    store.save_project(proj)

    config = MemoryConfig(data_dir=str(tmp_path))

    class TwoResponseMock:
        def __init__(self) -> None:
            self.calls = 0
            self.responses = [
                '{"summary": "Done.", "capabilities": [], "learnings": "new"}',
                "merged",
            ]

        def complete(self, system: str, user: str) -> str:
            resp = self.responses[min(self.calls, len(self.responses) - 1)]
            self.calls += 1
            return resp

    llm = TwoResponseMock()
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start(project_id="p1")
    manager.record_turn(session, "user", "hello")
    manager.end(session)

    run_digest = _make_run_digest(llm)
    run_digest(session.session_id, str(tmp_path))

    loaded = store.get_project("p1")
    assert loaded is not None
    assert loaded.learnings == "merged"


def test_run_digest_appends_session_id_to_project(tmp_path: pytest.TempPathFactory) -> None:
    """run_digest appends session_id to project.sessions."""
    store = LocalMemoryStore(str(tmp_path))
    proj = Project(project_id="p1", description="Test", status="active", sessions=[])
    store.save_project(proj)

    config = MemoryConfig(data_dir=str(tmp_path))
    llm = MockLLMClient('{"summary": "x", "capabilities": [], "learnings": ""}')
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start(project_id="p1")
    manager.record_turn(session, "user", "hi")
    manager.end(session)

    run_digest = _make_run_digest(llm)
    run_digest(session.session_id, str(tmp_path))

    loaded = store.get_project("p1")
    assert loaded is not None
    assert session.session_id in loaded.sessions


def test_run_digest_idempotent_session_id(tmp_path: pytest.TempPathFactory) -> None:
    """Calling run_digest twice: session_id appears only once in project.sessions."""
    store = LocalMemoryStore(str(tmp_path))
    proj = Project(project_id="p1", description="Test", status="active", sessions=[])
    store.save_project(proj)

    config = MemoryConfig(data_dir=str(tmp_path))
    llm = MockLLMClient('{"summary": "x", "capabilities": [], "learnings": ""}')
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start(project_id="p1")
    manager.record_turn(session, "user", "hi")
    manager.end(session)

    run_digest = _make_run_digest(llm)
    run_digest(session.session_id, str(tmp_path))
    # Re-save and call again to simulate retry
    store.save_active_session(session)
    run_digest(session.session_id, str(tmp_path))

    loaded = store.get_project("p1")
    assert loaded is not None
    assert loaded.sessions.count(session.session_id) == 1


def test_run_digest_no_project_id(tmp_path: pytest.TempPathFactory) -> None:
    """Session with project_id=None: digest saved, no crash."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    llm = MockLLMClient(DIGEST_JSON)
    manager = SessionManager(store, config, _TEST_SETTINGS, llm=MockLLMClient(DIGEST_JSON))

    session = manager.start(project_id=None)
    manager.record_turn(session, "user", "hi")
    manager.end(session)

    run_digest = _make_run_digest(llm)
    run_digest(session.session_id, str(tmp_path))

    assert store.get_digest(session.session_id) is not None
    assert store.load_active_session(session.session_id) is None

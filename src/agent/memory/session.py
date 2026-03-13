"""Session lifecycle management for active conversations."""

import subprocess
import sys
import uuid
from typing import NamedTuple

from agent.config.settings import Settings
from agent.logger import get_logger
from agent.memory.config import MemoryConfig
from agent.memory.llm import LLMClient, RealLLMClient
from agent.memory.models import ActiveSession, SessionDigest
from agent.memory.store import LocalMemoryStore

log = get_logger(__name__)


class EndResult(NamedTuple):
    """Result of SessionManager.end(): status and optional digest."""

    status: str  # "background" | "empty" | "failed"
    digest: SessionDigest | None = None


class SessionManager:
    """Handles active session creation, turn recording, and cleanup."""

    def __init__(
        self,
        store: LocalMemoryStore,
        config: MemoryConfig,
        settings: Settings,
        llm: LLMClient | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._settings = settings
        self._llm = llm or RealLLMClient(settings)

    def start(self, project_id: str | None = None) -> ActiveSession:
        """Create a new session, persist it, and return it."""
        session_id = uuid.uuid4().hex
        session = ActiveSession(session_id=session_id, project_id=project_id, messages=[])
        self._store.save_active_session(session)
        return session

    def record_turn(self, session: ActiveSession, role: str, content: str) -> ActiveSession:
        """Append a message to the session and persist."""
        session.messages.append({"role": role, "content": content})
        self._store.save_active_session(session)
        return session

    def end(self, session: ActiveSession) -> EndResult:
        """Spawn a background subprocess to generate the digest, then return immediately."""
        if not session.messages:
            self._store.delete_active_session(session.session_id)
            return EndResult("empty", None)

        # Session is already persisted on disk — hand off to the worker process.
        data_dir = str(self._store.data_dir)
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agent.memory.digest_worker",
                    "--session-id",
                    session.session_id,
                    "--data-dir",
                    data_dir,
                ],
                start_new_session=True,  # detach from parent so it survives CLI exit
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Digest worker spawned for session %s", session.session_id)
            return EndResult("background", None)
        except Exception as e:
            log.exception("Failed to spawn digest worker: %s", e)
            self._store.delete_active_session(session.session_id)
            return EndResult("failed", None)

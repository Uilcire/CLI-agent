"""Memory facade: single entry point for app, swallows all exceptions."""

from agent.config.settings import Settings
from agent.logger import get_logger
from agent.memory.config import MemoryConfig
from agent.memory.context import assemble_context
from agent.memory.models import ActiveSession, Project
from agent.memory.session import SessionManager
from agent.memory.store import LocalMemoryStore


class MemoryManager:
    """Facade over store, session, and context assembly. Never raises."""

    def __init__(self, data_dir: str, settings: Settings) -> None:
        self._config = MemoryConfig(data_dir=data_dir)
        self._store = LocalMemoryStore(data_dir)
        self._session_manager = SessionManager(self._store, self._config, settings)
        self._settings = settings
        self._session: ActiveSession | None = None
        self._log = get_logger(__name__)

    def on_startup(self, project_id: str | None = None) -> str:
        """Start a new session and return assembled context string. Returns '' on error."""
        try:
            self._session = self._session_manager.start(project_id)

            personality = self._store.get_personality()
            project = self._store.get_project(project_id) if project_id else None

            last_digest = None
            if project_id:
                digests = self._store.list_digests(project_id)
                last_digest = digests[-1] if digests else None

            return assemble_context(personality, project, last_digest, self._config)
        except Exception as e:
            self._log.exception("Memory on_startup failed: %s", e)
            return ""

    def on_user_turn(self, content: str) -> None:
        """Record user turn. Silent no-op on error or if no session."""
        if self._session is None:
            return
        try:
            self._session = self._session_manager.record_turn(
                self._session, "user", content
            )
        except Exception as e:
            self._log.exception("Memory on_user_turn failed: %s", e)

    def on_assistant_turn(self, content: str) -> None:
        """Record assistant turn. Silent no-op on error or if no session."""
        if self._session is None:
            return
        try:
            self._session = self._session_manager.record_turn(
                self._session, "assistant", content
            )
        except Exception as e:
            self._log.exception("Memory on_assistant_turn failed: %s", e)

    def on_exit(self) -> str | None:
        """End the session (delete from disk). Returns user-facing status message, or None on error/no session."""
        if self._session is None:
            return None
        try:
            result = self._session_manager.end(self._session)
            status_messages = {
                "background": "Session digest generating in background.",
                "empty": None,
                "failed": "Session ended (could not start background digest).",
            }
            return status_messages.get(result.status, f"Session ended ({result.status}).")
        except Exception as e:
            self._log.exception("Memory on_exit failed: %s", e)
            return f"Session ended (error: {e})."

    def find_project_for_cwd(self, cwd: str):
        """Look up the project for the given directory. Returns None if not found."""
        try:
            from agent.memory.onboarding import cwd_project_id
            pid = cwd_project_id(cwd)
            return self._store.get_project(pid)
        except Exception as e:
            self._log.exception("find_project_for_cwd failed: %s", e)
            return None

    def onboard_for_cwd(self, cwd: str, print_fn=print):
        """Run filesystem-based onboarding for cwd. Returns created project or None on error."""
        try:
            from agent.memory.llm import RealLLMClient
            from agent.memory.onboarding import detect_and_onboard
            llm = RealLLMClient(self._settings)
            return detect_and_onboard(cwd, self._store, llm, print_fn=print_fn)
        except Exception as e:
            self._log.exception("onboard_for_cwd failed: %s", e)
            print_fn(f"Project setup failed: {e}. Starting without project context.")
            return None

    def onboard(self, description: str):
        """Create a new project via onboarding. Returns project or None on error."""
        try:
            from agent.memory.llm import RealLLMClient
            from agent.memory.onboarding import onboard_project
            llm = RealLLMClient(self._settings)
            project = onboard_project(description, self._store, llm, print_fn=print)
            return project
        except Exception as e:
            self._log.exception("Memory onboard failed: %s", e)
            return None

    def handle_command(self, cmd: str) -> str | None:
        """Handle a /memory slash command. Returns output string or None if not a memory command."""
        try:
            from agent.memory.commands import handle_memory_command
            return handle_memory_command(cmd, self)
        except Exception as e:
            self._log.exception("Memory handle_command failed: %s", e)
            return f"Memory command failed: {e}"

"""AssistantMemoryManager — replaces the old MemoryManager facade."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from agent.config.settings import Settings

from .curator import Curator, rebuild_manifest
from .retrieval import RetrievalPipeline
from .schema import parse_frontmatter
from .signal_detector import SignalDetector
from .store import SCOPES, AssistantMemoryStore


logger = logging.getLogger(__name__)

_RECENT_TURN_CAP = 6  # 3 user + 3 assistant


class AssistantMemoryManager:
    """Replaces the old MemoryManager. Same public surface; new internals."""

    def __init__(self, data_dir: str, settings: Settings) -> None:
        self.data_dir = data_dir
        self.settings = settings
        self.store = AssistantMemoryStore(Path(data_dir))
        self.retrieval = RetrievalPipeline(self.store, settings)
        self.curator = Curator(self.store, settings)
        self.signal_detector = SignalDetector(self.store, settings)
        self.recent_turns: list[dict] = []
        self._active_session_messages: list[dict] = []
        self._latest_signals: dict = {}
        self._last_curator_thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------

    def on_startup(self) -> str:
        try:
            self.recent_turns = []
            self._active_session_messages = []

            immutable_core = self.store.read_immutable_core()
            soul = self.store.read_agent_soul()

            index_meta, _ = parse_frontmatter(self.store.read_index())
            user_summary = index_meta.get("user_summary", "")
            if not isinstance(user_summary, str):
                user_summary = ""

            current_context = self.store.read_current_context()

            parts: list[str] = []
            if immutable_core.strip():
                parts.append(f"# Agent Immutable Core\n\n{immutable_core.strip()}")
            if soul.strip():
                parts.append(f"# Agent Soul\n\n{soul.strip()}")
            if user_summary.strip():
                parts.append(f"# User\n\n{user_summary.strip()}")
            if current_context.strip():
                parts.append(f"# Current context\n\n{current_context.strip()}")
            return "\n\n".join(parts)
        except Exception as exc:
            logger.exception("AssistantMemoryManager.on_startup failed: %s", exc)
            return ""

    def retrieve_for_query(self, query: str) -> str:
        """Run two-stage retrieval and format a markdown block for system-prompt injection."""
        try:
            hints = [
                e.get("slug", "")
                for e in self._latest_signals.get("entities", [])
                if e.get("slug")
            ]
            result = self.retrieval.retrieve(query, list(self.recent_turns), hints=hints)
        except Exception as exc:
            logger.warning("retrieve_for_query failed: %s", exc)
            return ""

        try:
            files: list[str] = result.get("files", []) or []
            file_contents: dict[str, str] = result.get("file_contents", {}) or {}
            current_context = result.get("current_context", "") or ""
            user_summary = result.get("user_summary", "") or ""

            sections: list[str] = []
            for rel in files:
                body = file_contents.get(rel, "")
                if not body.strip():
                    continue
                sections.append(f"=== {rel} ===\n{body.strip()}")
            if current_context.strip():
                sections.append(f"=== context/current.md ===\n{current_context.strip()}")

            if not sections and not user_summary.strip():
                return ""

            header_lines = ["# Retrieved memories"]
            if user_summary.strip():
                header_lines.append(f"<!-- _index.md user_summary: {user_summary.strip()} -->")

            return "\n\n".join(header_lines + sections)
        except Exception as exc:
            logger.warning("retrieve_for_query format failed: %s", exc)
            return ""

    def on_user_turn(self, content: str) -> None:
        try:
            entry = {"role": "user", "content": content}
            self.recent_turns.append(entry)
            if len(self.recent_turns) > _RECENT_TURN_CAP:
                self.recent_turns = self.recent_turns[-_RECENT_TURN_CAP:]
            self._active_session_messages.append(entry)
        except Exception as exc:
            logger.warning("on_user_turn failed: %s", exc)
            return

        snapshot = list(self.recent_turns)
        detector = self.signal_detector

        def _run_detector() -> None:
            try:
                self._latest_signals = detector.detect(content, snapshot)
            except Exception as exc:
                logger.warning("signal detect failed: %s", exc)

        threading.Thread(target=_run_detector, daemon=True).start()

    def on_assistant_turn(self, content: str, run_curator: bool = True) -> None:
        try:
            entry = {"role": "assistant", "content": content}
            self.recent_turns.append(entry)
            if len(self.recent_turns) > _RECENT_TURN_CAP:
                self.recent_turns = self.recent_turns[-_RECENT_TURN_CAP:]
            self._active_session_messages.append(entry)
        except Exception as exc:
            logger.warning("on_assistant_turn append failed: %s", exc)
            return

        if not run_curator:
            return

        last_user = ""
        for t in reversed(self.recent_turns[:-1]):
            if t.get("role") == "user":
                last_user = t.get("content", "")
                break

        recent_snapshot = list(self.recent_turns)
        curator = self.curator

        def _run_curator() -> None:
            try:
                proposal = curator.propose_writes(
                    last_user, content, recent_snapshot, signals=self._latest_signals
                )
                curator.apply_writes(proposal, confirm_callback=None)
                curator.apply_manifest_updates(proposal.get("manifest_updates", []))
            except Exception as exc:
                logger.warning("curator post-turn failed: %s", exc)

        t = threading.Thread(target=_run_curator, daemon=True)
        t.start()
        self._last_curator_thread = t

    def on_exit(self) -> str | None:
        try:
            if not self._active_session_messages:
                return None
            if self._last_curator_thread is not None:
                try:
                    self._last_curator_thread.join(timeout=2.0)
                except Exception as exc:
                    logger.warning("curator thread join failed: %s", exc)
            messages = list(self._active_session_messages)
            curator = self.curator

            def _run() -> None:
                try:
                    curator.consolidate_session(messages)
                except Exception as exc:
                    logger.warning("consolidation pass failed: %s", exc)
                try:
                    curator.summarize_session(messages)
                except Exception as exc:
                    logger.warning("background session digest failed: %s", exc)

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            return "Dreaming... (consolidating + digesting in background)"
        except Exception as exc:
            logger.exception("on_exit failed: %s", exc)
            return f"Session ended (error: {exc})."

    # ---- slash commands --------------------------------------------------

    def handle_command(self, cmd: str) -> str | None:
        if not cmd or not cmd.startswith("/memory"):
            return None
        try:
            parts = cmd.strip().split(maxsplit=2)
            if len(parts) == 1 or (len(parts) == 2 and parts[1] == "help"):
                return (
                    "Memory commands:\n"
                    "  /memory list <scope>          — list files in scope\n"
                    "  /memory show <scope>/<file>   — print a file's contents\n"
                    "  /memory rebuild <scope>       — rebuild a scope manifest\n"
                    "  /memory current               — show context/current.md\n"
                    f"  scopes: {', '.join(SCOPES)}"
                )

            sub = parts[1]
            arg = parts[2] if len(parts) >= 3 else ""

            if sub == "list":
                if not arg:
                    return "Usage: /memory list <scope>"
                if arg not in SCOPES:
                    return f"Unknown scope: {arg}. Choose from: {', '.join(SCOPES)}"
                files = self.store.list_files(arg)
                return "\n".join(files) if files else f"(no files in {arg}/)"

            if sub == "show":
                if not arg:
                    return "Usage: /memory show <scope>/<file>"
                meta, body = self.store.read_file(arg)
                if not meta and not body:
                    return f"File not found: {arg}"
                from .schema import dump_frontmatter
                return dump_frontmatter(meta, body) if meta else body

            if sub == "rebuild":
                if not arg or arg not in SCOPES:
                    return f"Usage: /memory rebuild <scope>. Scopes: {', '.join(SCOPES)}"
                content = rebuild_manifest(self.store, arg, self.settings)
                self.store.write_manifest(arg, content)
                return f"Rebuilt {arg}/_manifest.md"

            if sub == "current":
                body = self.store.read_current_context()
                return body if body.strip() else "(context/current.md is empty)"

            return f"Unknown memory subcommand: {sub}. Try /memory help."
        except Exception as exc:
            logger.exception("handle_command failed: %s", exc)
            return f"Memory command failed: {exc}"

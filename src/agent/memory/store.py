"""Local JSON-backed memory store for personality, projects, digests, and sessions."""

import json
import os
from pathlib import Path

from agent.memory.models import ActiveSession, Personality, Project, SessionDigest


class LocalMemoryStore:
    """Persists memory models to JSON files under a data directory."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        os.makedirs(self._data_dir / "projects", exist_ok=True)
        os.makedirs(self._data_dir / "digests", exist_ok=True)
        os.makedirs(self._data_dir / "sessions", exist_ok=True)

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def _atomic_write(self, path: Path, data: dict) -> None:
        """Write JSON to a temp file, then atomically replace the target."""
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        os.replace(tmp_path, path)

    def get_personality(self) -> Personality | None:
        """Load personality from data_dir/personality.json. Returns None if not found."""
        path = self._data_dir / "personality.json"
        if not path.exists():
            return None
        text = path.read_text()
        return Personality.model_validate_json(text)

    def save_personality(self, p: Personality) -> None:
        """Save personality to data_dir/personality.json."""
        self._atomic_write(self._data_dir / "personality.json", p.model_dump())

    def get_project(self, project_id: str) -> Project | None:
        """Load project by ID. Returns None if not found."""
        path = self._data_dir / "projects" / f"{project_id}.json"
        if not path.exists():
            return None
        text = path.read_text()
        return Project.model_validate_json(text)

    def save_project(self, p: Project) -> None:
        """Save project to data_dir/projects/{project_id}.json."""
        self._atomic_write(self._data_dir / "projects" / f"{p.project_id}.json", p.model_dump())

    def list_projects(self) -> list[Project]:
        """List all projects, sorted by project_id."""
        projects_dir = self._data_dir / "projects"
        projects: list[Project] = []
        for path in projects_dir.glob("*.json"):
            text = path.read_text()
            projects.append(Project.model_validate_json(text))
        return sorted(projects, key=lambda p: p.project_id)

    def save_digest(self, d: SessionDigest) -> None:
        """Save session digest to data_dir/digests/{session_id}.json."""
        self._atomic_write(self._data_dir / "digests" / f"{d.session_id}.json", d.model_dump())

    def get_digest(self, session_id: str) -> SessionDigest | None:
        """Load digest by session_id. Returns None if not found."""
        path = self._data_dir / "digests" / f"{session_id}.json"
        if not path.exists():
            return None
        text = path.read_text()
        return SessionDigest.model_validate_json(text)

    def list_digests(self, project_id: str) -> list[SessionDigest]:
        """List digests for a project, sorted by timestamp ascending."""
        digests_dir = self._data_dir / "digests"
        digests: list[SessionDigest] = []
        for path in digests_dir.glob("*.json"):
            text = path.read_text()
            d = SessionDigest.model_validate_json(text)
            if d.project_id == project_id:
                digests.append(d)
        return sorted(digests, key=lambda d: d.timestamp)

    def save_active_session(self, s: ActiveSession) -> None:
        """Save active session to data_dir/sessions/{session_id}.json."""
        self._atomic_write(self._data_dir / "sessions" / f"{s.session_id}.json", s.model_dump())

    def load_active_session(self, session_id: str) -> ActiveSession | None:
        """Load active session by session_id. Returns None if not found."""
        path = self._data_dir / "sessions" / f"{session_id}.json"
        if not path.exists():
            return None
        text = path.read_text()
        return ActiveSession.model_validate_json(text)

    def list_active_sessions(self) -> list[dict]:
        """List active sessions with session_id, project_id, mtime; sorted by mtime descending."""
        sessions_dir = self._data_dir / "sessions"
        results: list[dict] = []
        for path in sessions_dir.glob("*.json"):
            text = path.read_text()
            s = ActiveSession.model_validate_json(text)
            mtime = path.stat().st_mtime
            results.append({
                "session_id": s.session_id,
                "project_id": s.project_id,
                "mtime": mtime,
            })
        return sorted(results, key=lambda x: x["mtime"], reverse=True)

    def delete_active_session(self, session_id: str) -> None:
        """Delete active session file. Silent no-op if missing."""
        path = self._data_dir / "sessions" / f"{session_id}.json"
        if path.exists():
            path.unlink()

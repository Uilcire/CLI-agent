"""Slash commands for memory inspection and management at runtime."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.memory.manager import MemoryManager


def handle_memory_command(cmd: str, manager: "MemoryManager") -> str | None:
    """
    Handle /memory slash commands. Returns formatted output string, or None if not a memory command.
    """
    try:
        if not cmd.startswith("/memory"):
            return None

        cmd = cmd.strip()

        if cmd == "/memory show":
            return _cmd_show(manager)
        if cmd == "/memory projects":
            return _cmd_projects(manager)
        if cmd == "/memory clear learnings":
            return _cmd_clear_learnings(manager)
        if cmd == "/memory help":
            return _cmd_help()
        if cmd == "/memory personality show":
            return _cmd_personality_show(manager)
        if cmd.startswith("/memory personality set soul "):
            text = cmd[len("/memory personality set soul ") :].strip().strip('"')
            return _cmd_personality_set_soul(manager, text)
        if cmd.startswith("/memory personality set core "):
            text = cmd[len("/memory personality set core ") :].strip().strip('"')
            return _cmd_personality_set_core(manager, text)
        if cmd == "/memory init":
            return _cmd_init(manager)

        return "Unknown memory command. Type '/memory help' for available commands."
    except Exception as e:
        return f"Memory command failed: {e}"


def _cmd_show(manager: "MemoryManager") -> str:
    session = manager._session
    session_id = session.session_id if session else "none"
    project = None
    if session and session.project_id:
        project = manager._store.get_project(session.project_id)

    tags = ", ".join(project.tags) if project else "-"
    capabilities = ", ".join(project.capabilities) if project else "-"
    sessions_recorded = len(project.sessions) if project else 0
    learnings = project.learnings if project else "-"
    if project and len(project.learnings) > 200:
        learnings = project.learnings[:200] + "..."

    return f"""## Memory Status
Session: {session_id}
Project: {project.description if project else "none"}
Tags: {tags}
Capabilities: {capabilities}
Sessions recorded: {sessions_recorded}
Learnings: {learnings}"""


def _cmd_projects(manager: "MemoryManager") -> str:
    projects = manager._store.list_projects()
    if not projects:
        return "No projects stored yet."

    lines = []
    for p in projects:
        desc = (p.description[:60] + "...") if len(p.description) > 60 else p.description
        tags = ", ".join(p.tags)
        n_sessions = len(p.sessions)
        lines.append(f"[{p.status}] {p.project_id} — {desc} | tags: {tags} | {n_sessions} sessions")
    return "\n".join(lines)


def _cmd_clear_learnings(manager: "MemoryManager") -> str:
    session = manager._session
    if not session or not session.project_id:
        return "No active project."

    project = manager._store.get_project(session.project_id)
    if project is None:
        return "No active project."

    project.learnings = ""
    project.last_summarized_session = None
    manager._store.save_project(project)
    return "Project learnings cleared."


def _cmd_personality_show(manager: "MemoryManager") -> str:
    personality = manager._store.get_personality()
    if personality is None:
        return "No soul configured. Run '/memory init' to set one up."
    return f"""## Soul
### Core (fixed)
{personality.immutable_core}

### Soul (evolving)
{personality.soul}"""


def _cmd_personality_set_soul(manager: "MemoryManager", text: str) -> str:
    if not text:
        return 'Usage: /memory personality set soul "<text>"'
    personality = manager._store.get_personality()
    if personality is None:
        return "No soul configured. Run '/memory init' first."
    personality.soul = text
    manager._store.save_personality(personality)
    return "Soul updated."


def _cmd_personality_set_core(manager: "MemoryManager", text: str) -> str:
    if not text:
        return 'Usage: /memory personality set core "<text>"'
    personality = manager._store.get_personality()
    if personality is None:
        return "No soul configured. Run '/memory init' first."
    from agent.memory.models import Personality

    new_personality = Personality(soul=personality.soul, immutable_core=text)
    manager._store.save_personality(new_personality)
    return "Immutable core updated. Note: this is permanent until changed again."


def _cmd_init(manager: "MemoryManager") -> str:
    if manager._store.get_personality() is not None:
        return "Soul already exists. Use '/memory personality show' to view it or '/memory personality set soul' to update it."
    from agent.memory.models import Personality

    p = Personality(
        soul="I am discovering my style through each conversation. I develop quirks and distinctive tendencies as I go.",
        immutable_core="I am honest. I never fabricate information. I acknowledge uncertainty.",
    )
    manager._store.save_personality(p)
    return """Soul initialised.

Immutable Core: I am honest. I never fabricate information. I acknowledge uncertainty.
Soul: I am discovering my style through each conversation. I develop quirks and distinctive tendencies as I go.

Use '/memory personality set soul "<text>"' to customise, or just keep chatting — I grow from every session."""



def _cmd_help() -> str:
    return """Available memory commands:
  /memory show              — current session and project info
  /memory projects          — list all stored projects
  /memory clear learnings   — clear accumulated learnings for current project
  /memory personality show      — view soul
  /memory personality set soul "<text>"  — update soul
  /memory personality set core "<text>"  — replace immutable core
  /memory init                  — create soul on first use
  /memory help              — show this help"""

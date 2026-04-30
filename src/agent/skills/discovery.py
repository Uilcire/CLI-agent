"""Filesystem scanner: discover SKILL.md files across known scope directories."""

import os
from pathlib import Path

from agent.logger import get_logger
from agent.skills.loader import parse_skill_file
from agent.skills.models import SkillRecord

log = get_logger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agents", ".claude"}
_MAX_DEPTH = 4

# Default skill source pool. The agent borrows the host's Claude Code skill
# library by default — convenient — and relies on AGENT.md to keep identity
# distinct from the tools. Override with AGENT_SKILL_SOURCES=agents to lock
# it down to project/.agents only.
_DEFAULT_SOURCES = "agents,claude"


def _enabled_sources() -> set[str]:
    """Parse AGENT_SKILL_SOURCES env var into a set of source names."""
    raw = os.environ.get("AGENT_SKILL_SOURCES") or _DEFAULT_SOURCES
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def get_scan_dirs(cwd: Path) -> list[tuple[Path, str, str]]:
    """
    Return (directory, scope, source) triples in priority order.

    Project-level skills override user-level skills on name collision.
    Within each scope, .agents/ is checked before .claude/.
    Source pools are gated by AGENT_SKILL_SOURCES (default: agents only).
    """
    sources = _enabled_sources()
    pool: list[tuple[Path, str, str]] = [
        (cwd / ".agents" / "skills", "project", "agents"),
        (cwd / ".claude" / "skills", "project", "claude"),
        (Path.home() / ".agents" / "skills", "user", "agents"),
        (Path.home() / ".claude" / "skills", "user", "claude"),
    ]
    return [(d, scope, src) for d, scope, src in pool if src in sources and d.is_dir()]


def _walk_skill_dirs(root: Path, depth: int = 0):
    """Yield paths to SKILL.md files found within root, up to _MAX_DEPTH levels deep."""
    if depth >= _MAX_DEPTH:
        return
    try:
        entries = list(root.iterdir())
    except PermissionError:
        return
    for entry in sorted(entries):
        try:
            if not entry.is_dir() or entry.name in _SKIP_DIRS:
                continue
            skill_file = entry / "SKILL.md"
            if skill_file.is_file():
                yield skill_file
            else:
                yield from _walk_skill_dirs(entry, depth + 1)
        except PermissionError:
            continue


def discover_skills(cwd: Path) -> dict[str, SkillRecord]:
    """
    Scan all skill directories and return a name→SkillRecord map.

    Collision rule: the first skill found with a given name (highest-priority
    scope) wins. A warning is logged when a skill is shadowed.
    """
    skills: dict[str, SkillRecord] = {}
    seen_paths: set[Path] = set()

    for scan_dir, scope, source in get_scan_dirs(cwd):
        for skill_path in _walk_skill_dirs(scan_dir):
            try:
                resolved = skill_path.resolve()
            except OSError:
                resolved = skill_path
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            record = parse_skill_file(skill_path, scope=scope)
            if record is None:
                continue
            record.source = source
            if record.name in skills:
                existing = skills[record.name]
                log.warning(
                    "Skill '%s' from %s shadowed by %s",
                    record.name,
                    skill_path,
                    existing.location,
                )
                continue
            skills[record.name] = record
            log.debug("Discovered skill '%s' (%s) from %s", record.name, scope, skill_path)

    if skills:
        log.info("Skills discovered: %s", list(skills.keys()))
    else:
        log.debug("No skills found in any scan directory")

    return skills

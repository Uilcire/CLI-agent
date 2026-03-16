"""Filesystem scanner: discover SKILL.md files across known scope directories."""

import logging
from pathlib import Path

from agent.skills.loader import parse_skill_file
from agent.skills.models import SkillRecord

log = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agents", ".claude"}
_MAX_DEPTH = 4


def get_scan_dirs(cwd: Path) -> list[tuple[Path, str]]:
    """
    Return (directory, scope) pairs in priority order (highest priority first).

    Project-level skills override user-level skills on name collision.
    Within each scope, .claude is checked before .agents.
    """
    candidates: list[tuple[Path, str]] = [
        (cwd / ".claude" / "skills", "project"),
        (cwd / ".agents" / "skills", "project"),
        (Path.home() / ".claude" / "skills", "user"),
        (Path.home() / ".agents" / "skills", "user"),
    ]
    return [(d, scope) for d, scope in candidates if d.is_dir()]


def _walk_skill_dirs(root: Path, depth: int = 0):
    """Yield paths to SKILL.md files found within root, up to _MAX_DEPTH levels deep."""
    if depth > _MAX_DEPTH:
        return
    try:
        entries = list(root.iterdir())
    except PermissionError:
        return
    for entry in sorted(entries):
        if not entry.is_dir() or entry.name in _SKIP_DIRS:
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            yield skill_file
        else:
            yield from _walk_skill_dirs(entry, depth + 1)


def discover_skills(cwd: Path) -> dict[str, SkillRecord]:
    """
    Scan all skill directories and return a name→SkillRecord map.

    Collision rule: the first skill found with a given name (highest-priority
    scope) wins. A warning is logged when a skill is shadowed.
    """
    skills: dict[str, SkillRecord] = {}

    for scan_dir, scope in get_scan_dirs(cwd):
        for skill_path in _walk_skill_dirs(scan_dir):
            record = parse_skill_file(skill_path, scope=scope)
            if record is None:
                continue
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

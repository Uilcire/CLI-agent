"""Parse SKILL.md files into SkillRecord objects."""

import re
from pathlib import Path

import yaml

from agent.logger import get_logger
from agent.skills.models import SkillRecord

log = get_logger(__name__)


_DESCRIPTION_TRIGGERS = (
    "use when",
    "用于",
    "用来",
    "适用",
    "trigger",
    "when the user",
    "when to",
)


def parse_skill_file(path: Path, scope: str = "project") -> SkillRecord | None:
    """
    Parse a SKILL.md file and return a SkillRecord, or None if the file is invalid.

    Validation rules:
    - Missing or empty description → skip (return None)
    - Completely unparseable YAML → skip (return None)
    - Name mismatch with parent dir or name > 64 chars → warn, load anyway
    - Description shorter than 30 chars or missing trigger phrase → warn, load anyway
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as e:
        log.warning("Cannot read skill file %s: %s", path, e)
        return None

    # Require opening ---, then content, then closing ---
    parts = text.split("---", 2)
    if len(parts) < 3:
        log.warning("Skill file %s has no valid frontmatter delimiters, skipping", path)
        return None

    yaml_block = parts[1].strip()
    body = parts[2].strip()

    data = _parse_yaml(yaml_block, path)
    if data is None:
        return None

    description = str(data.get("description", "")).strip()
    if not description:
        log.warning("Skill file %s has no description, skipping", path)
        return None

    name = str(data.get("name", "")).strip()
    if not name:
        name = path.parent.name

    if len(name) > 64:
        log.warning(
            "Skill '%s' name exceeds 64 chars (from %s), loading anyway", name, path
        )

    expected_name = path.parent.name
    if name != expected_name:
        log.warning(
            "Skill name '%s' doesn't match directory '%s' (from %s), loading anyway",
            name,
            expected_name,
            path,
        )

    desc_lower = description.lower()
    if len(description) < 30 or not any(t in desc_lower for t in _DESCRIPTION_TRIGGERS):
        log.warning(
            "Skill '%s' description may be too short or lacks a clear trigger phrase "
            "(consider including 'use when' / '用于' / 'trigger' etc.): %s",
            name,
            path,
        )

    raw_tools = data.get("allowed-tools")
    if raw_tools is None:
        raw_tools = data.get("tools")
    allowed_tools = _parse_allowed_tools(raw_tools, path)

    return SkillRecord(
        name=name,
        description=description,
        location=path.resolve(),
        body=body,
        scope=scope,  # type: ignore[arg-type]
        allowed_tools=allowed_tools,
    )


def _parse_yaml(yaml_block: str, path: Path) -> dict | None:
    """Try yaml.safe_load; on failure attempt a colon-value fallback, then give up."""
    try:
        data = yaml.safe_load(yaml_block)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass

    # Fallback: wrap unquoted values that contain a colon in double-quotes.
    # Matches lines like: description: Use this when: the user asks about PDFs
    fixed = re.sub(
        r'^(\s*[\w][\w-]*\s*:\s*)(.+:.+)$',
        lambda m: m.group(1) + '"' + m.group(2).replace('"', '\\"') + '"',
        yaml_block,
        flags=re.MULTILINE,
    )
    try:
        data = yaml.safe_load(fixed)
        if isinstance(data, dict):
            log.warning(
                "Skill file %s had malformed YAML; loaded with fallback parser", path
            )
            return data
    except yaml.YAMLError:
        pass

    log.warning("Skill file %s has unparseable YAML, skipping", path)
    return None


def _parse_allowed_tools(raw: object, path: Path) -> list[str]:
    """
    Parse the allowed-tools / tools list from frontmatter.

    Each entry may be:
    - a scalar string like "Bash" or "Bash(git status:*)" → kept as-is
    - a legacy dict with a "name" field → coerced to that bare name
    Logs a single coercion warning if any dict entries were degraded.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        log.warning(
            "Skill file %s has non-list 'allowed-tools'/'tools' field, ignoring", path
        )
        return []

    result: list[str] = []
    coerced = False
    dropped = 0
    for entry in raw:
        if isinstance(entry, str):
            s = entry.strip()
            if s:
                result.append(s)
            else:
                dropped += 1
        elif isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            if name:
                result.append(name)
                coerced = True
            else:
                dropped += 1
        else:
            dropped += 1

    if coerced:
        log.warning(
            "Skill file %s has legacy dict-style tool entries; coerced to bare names. "
            "Skills should use Claude Code's allowed-tools whitelist format.",
            path,
        )
    if dropped:
        log.warning(
            "Skill file %s dropped %d unparseable tool entries (missing name, "
            "wrong type, or empty)",
            path,
            dropped,
        )

    return result

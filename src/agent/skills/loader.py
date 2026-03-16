"""Parse SKILL.md files into SkillRecord objects."""

import logging
import re
from pathlib import Path

import yaml

from agent.skills.models import SkillRecord

log = logging.getLogger(__name__)


def parse_skill_file(path: Path, scope: str = "project") -> SkillRecord | None:
    """
    Parse a SKILL.md file and return a SkillRecord, or None if the file is invalid.

    Validation rules:
    - Missing or empty description → skip (return None)
    - Completely unparseable YAML → skip (return None)
    - Name mismatch with parent dir or name > 64 chars → warn, load anyway
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
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

    return SkillRecord(
        name=name,
        description=description,
        location=path.resolve(),
        body=body,
        scope=scope,  # type: ignore[arg-type]
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

"""Data models for the skills subsystem."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class SkillRecord:
    """Represents a single discovered skill."""

    name: str
    description: str
    location: Path          # absolute path to the SKILL.md file
    body: str               # markdown body with YAML frontmatter stripped
    scope: Literal["project", "user"]

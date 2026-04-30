"""SkillManager: catalog facade over discovered skills."""

from xml.sax.saxutils import escape

from agent.skills.models import SkillRecord


class SkillManager:
    def __init__(self, skills: dict[str, SkillRecord]) -> None:
        self._skills = skills

    def is_empty(self) -> bool:
        return len(self._skills) == 0

    def get(self, name: str) -> SkillRecord | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def get_body(self, name: str) -> str | None:
        """Return the SKILL.md body of the named skill, or None if not found."""
        record = self._skills.get(name)
        return record.body if record else None

    def catalog_xml(self) -> str:
        """
        Build a minimal XML catalog block for injection into the system prompt.

        Progressive disclosure: only name + description are exposed at startup.
        Tool whitelists, location, and body are loaded on demand via read_skill.
        """
        lines = ["<available_skills>"]
        for skill in self._skills.values():
            src_attr = escape(skill.source, {'"': "&quot;"})
            lines.append(f'  <skill source="{src_attr}">')
            lines.append(f"    <name>{escape(skill.name)}</name>")
            lines.append(f"    <description>{escape(skill.description)}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    @property
    def skills(self) -> dict[str, SkillRecord]:
        return self._skills

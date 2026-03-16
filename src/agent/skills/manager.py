"""SkillManager: catalog facade over discovered skills."""

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

    def catalog_xml(self) -> str:
        """Build an XML catalog block for injection into the system prompt."""
        lines = ["<available_skills>"]
        for skill in self._skills.values():
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{skill.description}</description>")
            lines.append(f"    <location>{skill.location}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    @property
    def skills(self) -> dict[str, SkillRecord]:
        return self._skills

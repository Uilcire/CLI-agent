"""read_skill tool: load full skill instructions into conversation context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.state import ConversationState
    from agent.skills.manager import SkillManager


def read_skill(
    name: str,
    skill_manager: "SkillManager",
    state: "ConversationState",
) -> str:
    """
    Load the full instructions for a named skill into context.

    Returns a <skill_content> block with the skill body, the skill directory
    path, a listing of any bundled resource files (not eagerly read), and the
    skill's allowed-tools whitelist (informational only — not enforced).

    Re-reading the same skill is allowed; the model may want to refresh.
    """
    skill = skill_manager.get(name)
    if skill is None:
        return f"Error: skill '{name}' not found."

    state.activated_skills.add(name)

    skill_dir: Path = skill.location.parent
    try:
        resources = sorted(
            f.name for f in skill_dir.iterdir() if f.name != "SKILL.md"
        )
    except OSError:
        resources = []

    lines = [f'<skill_content name="{name}">']
    lines.append(skill.body)
    lines.append("")
    lines.append(f"Skill directory: {skill_dir}")
    lines.append(
        "Relative paths in this skill are relative to the skill directory."
    )

    if resources:
        lines.append("<skill_resources>")
        for r in resources:
            lines.append(f"  <file>{r}</file>")
        lines.append("</skill_resources>")

    if skill.allowed_tools:
        lines.append("<allowed_tools>")
        for entry in skill.allowed_tools:
            lines.append(f"  <tool>{entry}</tool>")
        lines.append("</allowed_tools>")
        lines.append(
            "Note: allowed_tools is informational. Use the bash tool for any "
            "shell commands the skill instructs you to run."
        )

    lines.append("</skill_content>")
    return "\n".join(lines)

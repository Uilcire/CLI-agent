"""Tests for the skills subsystem: loader, discovery, manager, and activate_skill tool."""

from pathlib import Path

import pytest

from agent.core.state import ConversationState
from agent.skills.discovery import discover_skills
from agent.skills.loader import parse_skill_file
from agent.skills.manager import SkillManager
from agent.tools.activate_skill import activate_skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_skill_dir(tmp_path: Path, name: str, content: str) -> Path:
    """Create a skill directory with a SKILL.md file and return the directory."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


VALID_SKILL_MD = """\
---
name: pdf-processing
description: Extract PDF text, fill forms, and merge files.
---

## When to use this skill
Use this skill when the user needs to work with PDF files.

## Steps
1. Load the PDF
2. Process it
"""

MISSING_DESCRIPTION_MD = """\
---
name: no-desc
---

Body content here.
"""

MALFORMED_YAML_MD = """\
---
name: tricky-skill
description: Use this when: the user asks about something
---

Body of tricky skill.
"""

UNPARSEABLE_YAML_MD = """\
---
: : : completely broken yaml {{{
---

Body here.
"""

NO_FRONTMATTER_MD = "Just some markdown text with no frontmatter."


# ---------------------------------------------------------------------------
# loader.py — parse_skill_file
# ---------------------------------------------------------------------------

class TestParseSkillFile:
    def test_valid_skill(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        record = parse_skill_file(skill_dir / "SKILL.md", scope="project")

        assert record is not None
        assert record.name == "pdf-processing"
        assert record.description == "Extract PDF text, fill forms, and merge files."
        assert "When to use this skill" in record.body
        assert record.scope == "project"
        assert record.location == (skill_dir / "SKILL.md").resolve()

    def test_body_strips_frontmatter(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert "---" not in record.body
        assert "name: pdf-processing" not in record.body

    def test_missing_description_returns_none(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "no-desc", MISSING_DESCRIPTION_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is None

    def test_malformed_yaml_colon_fallback(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "tricky-skill", MALFORMED_YAML_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert record.name == "tricky-skill"
        assert "the user asks about something" in record.description

    def test_unparseable_yaml_returns_none(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "bad-skill", UNPARSEABLE_YAML_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is None

    def test_no_frontmatter_returns_none(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "bare-skill", NO_FRONTMATTER_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is None

    def test_name_fallback_to_directory(self, tmp_path):
        content = "---\ndescription: A skill with no name field.\n---\nBody."
        skill_dir = make_skill_dir(tmp_path, "my-skill-dir", content)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert record.name == "my-skill-dir"

    def test_user_scope(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        record = parse_skill_file(skill_dir / "SKILL.md", scope="user")

        assert record is not None
        assert record.scope == "user"

    def test_missing_file_returns_none(self, tmp_path):
        record = parse_skill_file(tmp_path / "nonexistent" / "SKILL.md")
        assert record is None


# ---------------------------------------------------------------------------
# discovery.py — discover_skills
# ---------------------------------------------------------------------------

class TestDiscoverSkills:
    def _make_skills_root(self, tmp_path: Path) -> Path:
        """Create a fake project directory with a .claude/skills/ subtree."""
        project = tmp_path / "project"
        project.mkdir()
        return project

    def test_single_project_skill(self, tmp_path):
        project = self._make_skills_root(tmp_path)
        skills_dir = project / ".claude" / "skills"
        make_skill_dir(skills_dir, "pdf-processing", VALID_SKILL_MD)

        result = discover_skills(project)

        assert "pdf-processing" in result
        assert result["pdf-processing"].scope == "project"

    def test_project_scope_beats_user_scope(self, tmp_path, monkeypatch):
        project = self._make_skills_root(tmp_path)

        # Project-level skill
        project_skills = project / ".claude" / "skills"
        make_skill_dir(project_skills, "pdf-processing", VALID_SKILL_MD)

        # User-level skill with same name but different description
        user_home = tmp_path / "home"
        user_home.mkdir()
        user_skills = user_home / ".claude" / "skills"
        user_content = VALID_SKILL_MD.replace(
            "Extract PDF text", "User-level PDF skill"
        )
        make_skill_dir(user_skills, "pdf-processing", user_content)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

        result = discover_skills(project)

        assert result["pdf-processing"].scope == "project"
        assert "Extract PDF text" in result["pdf-processing"].description

    def test_skips_git_and_node_modules(self, tmp_path):
        project = self._make_skills_root(tmp_path)
        skills_root = project / ".claude" / "skills"
        skills_root.mkdir(parents=True)

        # These should be skipped
        for skip_dir in [".git", "node_modules", "__pycache__"]:
            skip = skills_root / skip_dir
            skip.mkdir()
            (skip / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")

        result = discover_skills(project)
        assert len(result) == 0

    def test_no_skills_returns_empty(self, tmp_path):
        project = self._make_skills_root(tmp_path)
        result = discover_skills(project)
        assert result == {}

    def test_multiple_skills_discovered(self, tmp_path):
        project = self._make_skills_root(tmp_path)
        skills_dir = project / ".claude" / "skills"

        content_b = "---\nname: data-analysis\ndescription: Analyze datasets.\n---\nBody."
        make_skill_dir(skills_dir, "pdf-processing", VALID_SKILL_MD)
        make_skill_dir(skills_dir, "data-analysis", content_b)

        result = discover_skills(project)
        assert "pdf-processing" in result
        assert "data-analysis" in result


# ---------------------------------------------------------------------------
# manager.py — SkillManager
# ---------------------------------------------------------------------------

class TestSkillManager:
    def _make_record(self, tmp_path, name="pdf-processing"):
        skill_dir = make_skill_dir(tmp_path, name, VALID_SKILL_MD)
        record = parse_skill_file(skill_dir / "SKILL.md", scope="project")
        assert record is not None
        return record

    def test_is_empty_true_when_no_skills(self):
        mgr = SkillManager({})
        assert mgr.is_empty()

    def test_is_empty_false_when_skills_present(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        assert not mgr.is_empty()

    def test_get_known_skill(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        assert mgr.get("pdf-processing") is record

    def test_get_unknown_skill_returns_none(self, tmp_path):
        mgr = SkillManager({})
        assert mgr.get("nonexistent") is None

    def test_catalog_xml_structure(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        xml = mgr.catalog_xml()

        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<name>pdf-processing</name>" in xml
        assert "<description>" in xml
        assert "<location>" in xml

    def test_catalog_xml_empty_manager(self):
        mgr = SkillManager({})
        xml = mgr.catalog_xml()
        assert "<available_skills>" in xml
        assert "<skill>" not in xml

    def test_names_returns_all_skill_names(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        assert mgr.names() == ["pdf-processing"]


# ---------------------------------------------------------------------------
# activate_skill tool
# ---------------------------------------------------------------------------

class TestActivateSkill:
    def _setup(self, tmp_path, extra_files: list[str] | None = None):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        if extra_files:
            for fname in extra_files:
                (skill_dir / fname).write_text("# resource", encoding="utf-8")
        record = parse_skill_file(skill_dir / "SKILL.md", scope="project")
        assert record is not None
        mgr = SkillManager({record.name: record})
        state = ConversationState()
        return mgr, state

    def test_first_activation_returns_skill_content(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = activate_skill("pdf-processing", mgr, state)

        assert '<skill_content name="pdf-processing">' in result
        assert "When to use this skill" in result
        assert "</skill_content>" in result

    def test_first_activation_marks_skill_as_activated(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        activate_skill("pdf-processing", mgr, state)

        assert "pdf-processing" in state.activated_skills

    def test_second_activation_returns_already_loaded(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        activate_skill("pdf-processing", mgr, state)
        result = activate_skill("pdf-processing", mgr, state)

        assert "already loaded" in result

    def test_unknown_skill_returns_error(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = activate_skill("nonexistent", mgr, state)

        assert result.startswith("Error:")

    def test_bundled_resources_listed(self, tmp_path):
        mgr, state = self._setup(tmp_path, extra_files=["extract.py", "guide.md"])
        result = activate_skill("pdf-processing", mgr, state)

        assert "<skill_resources>" in result
        assert "<file>extract.py</file>" in result
        assert "<file>guide.md</file>" in result

    def test_no_resources_omits_skill_resources_block(self, tmp_path):
        mgr, state = self._setup(tmp_path, extra_files=None)
        result = activate_skill("pdf-processing", mgr, state)

        assert "<skill_resources>" not in result

    def test_skill_directory_path_included(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = activate_skill("pdf-processing", mgr, state)

        assert "Skill directory:" in result

    def test_activated_skills_not_duplicated_in_state(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        activate_skill("pdf-processing", mgr, state)
        activate_skill("pdf-processing", mgr, state)

        assert len([s for s in state.activated_skills if s == "pdf-processing"]) == 1


# ---------------------------------------------------------------------------
# ConversationState — activated_skills field
# ---------------------------------------------------------------------------

class TestConversationStateActivatedSkills:
    def test_activated_skills_starts_empty(self):
        state = ConversationState()
        assert state.activated_skills == set()

    def test_activated_skills_can_be_updated(self):
        state = ConversationState()
        state.activated_skills.add("my-skill")
        assert "my-skill" in state.activated_skills

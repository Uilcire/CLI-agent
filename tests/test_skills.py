"""Tests for the skills subsystem: loader, discovery, manager, and read_skill tool."""

import logging
from pathlib import Path

import pytest

from agent.core.state import ConversationState
from agent.skills.discovery import discover_skills
from agent.skills.loader import parse_skill_file
from agent.skills.manager import SkillManager
from agent.tools.read_skill import read_skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_skill_dir(tmp_path: Path, name: str, content: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


VALID_SKILL_MD = """\
---
name: pdf-processing
description: Use when the user needs to extract PDF text, fill forms, or merge files.
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

SKILL_WITH_ALLOWED_TOOLS_MD = """\
---
name: deploy-skill
description: Use when the user wants to deploy services to production.
allowed-tools:
  - Bash
  - Bash(git status:*)
  - Read
---

Skill body.
"""

SKILL_WITH_LEGACY_DICT_TOOLS_MD = """\
---
name: legacy-skill
description: Use when migrating from the legacy dict-tool skill format.
tools:
  - name: say_hi
    description: Greet someone.
    command: echo Hello
  - name: list_things
    command: ls
---

Body.
"""


# ---------------------------------------------------------------------------
# loader.py — parse_skill_file
# ---------------------------------------------------------------------------


class TestParseSkillFile:
    def test_valid_skill(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        record = parse_skill_file(skill_dir / "SKILL.md", scope="project")

        assert record is not None
        assert record.name == "pdf-processing"
        assert "Use when" in record.description
        assert "When to use this skill" in record.body
        assert record.scope == "project"
        assert record.location == (skill_dir / "SKILL.md").resolve()
        assert record.allowed_tools == []

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
        content = (
            "---\ndescription: Use when working with skills that have no name field.\n"
            "---\nBody."
        )
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

    def test_allowed_tools_string_list(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "deploy-skill", SKILL_WITH_ALLOWED_TOOLS_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert record.allowed_tools == ["Bash", "Bash(git status:*)", "Read"]
        assert all(isinstance(s, str) for s in record.allowed_tools)

    def test_legacy_dict_tools_coerced_to_names(self, tmp_path, caplog):
        skill_dir = make_skill_dir(
            tmp_path, "legacy-skill", SKILL_WITH_LEGACY_DICT_TOOLS_MD
        )
        with caplog.at_level(logging.WARNING):
            record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert record.allowed_tools == ["say_hi", "list_things"]
        # One coercion warning total — not one per entry.
        coercion_warnings = [
            r for r in caplog.records if "legacy dict-style" in r.getMessage()
        ]
        assert len(coercion_warnings) == 1

    def test_short_description_warns(self, tmp_path, caplog):
        content = "---\nname: terse\ndescription: Tiny.\n---\nBody."
        skill_dir = make_skill_dir(tmp_path, "terse", content)
        with caplog.at_level(logging.WARNING):
            record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert any(
            "too short or lacks a clear trigger" in r.getMessage()
            for r in caplog.records
        )

    def test_description_without_trigger_warns(self, tmp_path, caplog):
        content = (
            "---\nname: vague\ndescription: A general purpose tool that does stuff well.\n"
            "---\nBody."
        )
        skill_dir = make_skill_dir(tmp_path, "vague", content)
        with caplog.at_level(logging.WARNING):
            record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert any(
            "too short or lacks a clear trigger" in r.getMessage()
            for r in caplog.records
        )

    def test_good_description_no_warn(self, tmp_path, caplog):
        skill_dir = make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        with caplog.at_level(logging.WARNING):
            record = parse_skill_file(skill_dir / "SKILL.md")

        assert record is not None
        assert not any(
            "too short or lacks a clear trigger" in r.getMessage()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# discovery.py — discover_skills
# ---------------------------------------------------------------------------

class TestDiscoverSkills:
    def _make_skills_root(self, tmp_path: Path) -> Path:
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

        project_skills = project / ".claude" / "skills"
        make_skill_dir(project_skills, "pdf-processing", VALID_SKILL_MD)

        user_home = tmp_path / "home"
        user_home.mkdir()
        user_skills = user_home / ".claude" / "skills"
        user_content = VALID_SKILL_MD.replace(
            "extract PDF text", "User-level PDF skill text"
        )
        make_skill_dir(user_skills, "pdf-processing", user_content)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

        result = discover_skills(project)
        assert result["pdf-processing"].scope == "project"

    def test_skips_git_and_node_modules(self, tmp_path):
        project = self._make_skills_root(tmp_path)
        skills_root = project / ".claude" / "skills"
        skills_root.mkdir(parents=True)

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

        content_b = (
            "---\nname: data-analysis\n"
            "description: Use when the user wants to analyze datasets or run stats.\n"
            "---\nBody."
        )
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

    def test_get_unknown_skill_returns_none(self):
        mgr = SkillManager({})
        assert mgr.get("nonexistent") is None

    def test_get_body_returns_body(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        body = mgr.get_body("pdf-processing")
        assert body is not None
        assert "When to use this skill" in body

    def test_get_body_unknown_returns_none(self):
        mgr = SkillManager({})
        assert mgr.get_body("nope") is None

    def test_catalog_xml_minimal_structure(self, tmp_path):
        record = self._make_record(tmp_path)
        mgr = SkillManager({record.name: record})
        xml = mgr.catalog_xml()

        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<name>pdf-processing</name>" in xml
        assert "<description>" in xml
        # Catalog is intentionally minimal: no tools, no location.
        assert "<tools>" not in xml
        assert "<location>" not in xml

    def test_catalog_xml_omits_allowed_tools(self, tmp_path):
        skill_dir = make_skill_dir(tmp_path, "deploy-skill", SKILL_WITH_ALLOWED_TOOLS_MD)
        record = parse_skill_file(skill_dir / "SKILL.md")
        assert record is not None
        mgr = SkillManager({record.name: record})
        xml = mgr.catalog_xml()

        assert "Bash" not in xml
        assert "<allowed_tools>" not in xml

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
# read_skill tool
# ---------------------------------------------------------------------------

class TestReadSkill:
    def _setup(self, tmp_path, content=VALID_SKILL_MD, name="pdf-processing", extras=None):
        skill_dir = make_skill_dir(tmp_path, name, content)
        if extras:
            for fname in extras:
                (skill_dir / fname).write_text("# resource", encoding="utf-8")
        record = parse_skill_file(skill_dir / "SKILL.md", scope="project")
        assert record is not None
        mgr = SkillManager({record.name: record})
        state = ConversationState()
        return mgr, state

    def test_first_read_returns_skill_content(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = read_skill("pdf-processing", mgr, state)

        assert '<skill_content name="pdf-processing">' in result
        assert "When to use this skill" in result
        assert "</skill_content>" in result

    def test_read_marks_skill_in_state(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        read_skill("pdf-processing", mgr, state)
        assert "pdf-processing" in state.activated_skills

    def test_re_read_is_allowed(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        first = read_skill("pdf-processing", mgr, state)
        second = read_skill("pdf-processing", mgr, state)
        # No "already loaded" rejection — both calls return content.
        assert "<skill_content" in first
        assert "<skill_content" in second
        assert "already loaded" not in second.lower()

    def test_unknown_skill_returns_error(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = read_skill("nonexistent", mgr, state)
        assert result.startswith("Error:")

    def test_bundled_resources_listed(self, tmp_path):
        mgr, state = self._setup(tmp_path, extras=["extract.py", "guide.md"])
        result = read_skill("pdf-processing", mgr, state)

        assert "<skill_resources>" in result
        assert "<file>extract.py</file>" in result
        assert "<file>guide.md</file>" in result

    def test_no_resources_omits_block(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = read_skill("pdf-processing", mgr, state)
        assert "<skill_resources>" not in result

    def test_allowed_tools_block_displayed(self, tmp_path):
        mgr, state = self._setup(
            tmp_path, content=SKILL_WITH_ALLOWED_TOOLS_MD, name="deploy-skill"
        )
        result = read_skill("deploy-skill", mgr, state)

        assert "<allowed_tools>" in result
        assert "<tool>Bash</tool>" in result
        assert "<tool>Read</tool>" in result

    def test_skill_directory_path_included(self, tmp_path):
        mgr, state = self._setup(tmp_path)
        result = read_skill("pdf-processing", mgr, state)
        assert "Skill directory:" in result


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


# ---------------------------------------------------------------------------
# bash tool
# ---------------------------------------------------------------------------

from agent.tools.bash import run_bash


class TestRunBash:
    def test_simple_echo(self):
        out = run_bash("echo hello")
        assert "hello" in out

    def test_pipes_supported(self):
        out = run_bash("echo a b c | tr ' ' '\\n' | wc -l")
        # Five-line file? Expect "3" somewhere.
        assert "3" in out

    def test_nonzero_returns_error(self):
        out = run_bash("false")
        assert out.startswith("Error: command exited with code 1")

    def test_invalid_cwd_returns_error(self):
        out = run_bash("echo hi", cwd="/nonexistent/path/xyz")
        assert out.startswith("Error: cwd does not exist")

    def test_custom_cwd(self, tmp_path):
        (tmp_path / "marker.txt").write_text("ok")
        out = run_bash("ls", cwd=str(tmp_path))
        assert "marker.txt" in out

    def test_timeout(self):
        out = run_bash("sleep 5", timeout=1)
        assert "timed out" in out

    def test_no_output(self):
        out = run_bash("true")
        assert out == "(no output)"

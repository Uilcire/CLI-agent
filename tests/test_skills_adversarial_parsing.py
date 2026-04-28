"""Adversarial tests for the skills loader/parser/discovery/manager.

These tests exist to BREAK the parser. Each test is focused on one
specific edge case so the failure mode is obvious from the test name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from agent.skills.discovery import discover_skills
from agent.skills.loader import parse_skill_file
from agent.skills.manager import SkillManager
from agent.skills.models import SkillRecord


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def write_skill(parent: Path, dir_name: str, content: str) -> Path:
    skill_dir = parent / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    p = skill_dir / "SKILL.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Stub Path.home() so discover_skills doesn't see the real user's skills."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


# ---------------------------------------------------------------------------
# 1. YAML adversaries
# ---------------------------------------------------------------------------


def test_no_closing_delimiter_returns_none(tmp_path, caplog):
    p = write_skill(
        tmp_path,
        "no-close",
        "---\nname: no-close\ndescription: Use when something happens to test things\n",
    )
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is None
    assert any("frontmatter" in r.message.lower() for r in caplog.records)


def test_only_delimiters_no_yaml_inside(tmp_path, caplog):
    p = write_skill(tmp_path, "empty-fm", "---\n---\nbody only\n")
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    # Empty YAML → no description → skip
    assert record is None


def test_yaml_with_tab_in_unquoted_value_rejected(tmp_path, caplog):
    """Documents that a literal tab inside an unquoted scalar makes PyYAML
    treat the value as unparseable. The fallback parser doesn't help either,
    because the value doesn't contain a colon."""
    content = (
        "---\n"
        "name: tab-skill\n"
        "description: Use when something\thappens to test the parser thoroughly\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "tab-skill", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    # Actual behavior: rejected as unparseable.
    assert record is None
    assert any("unparseable YAML" in r.message for r in caplog.records)


def test_yaml_with_tab_in_quoted_value_accepted(tmp_path):
    """Same tab survives if the value is explicitly quoted."""
    content = (
        "---\n"
        "name: tab-skill\n"
        'description: "Use when something\thappens to test the parser thoroughly"\n'
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "tab-skill", content)
    record = parse_skill_file(p)
    assert record is not None
    assert "\t" in record.description


def test_description_with_colon_uses_fallback_parser(tmp_path, caplog):
    content = (
        "---\n"
        "name: colon-skill\n"
        "description: Use when: things break and need investigating right away\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "colon-skill", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    # The fallback parser quotes the value; description should round-trip
    assert "things break" in record.description
    # And it should warn that the fallback parser was used
    assert any("fallback parser" in r.message for r in caplog.records)


def test_description_multiline_block_scalar(tmp_path):
    content = (
        "---\n"
        "name: multiline-skill\n"
        "description: |\n"
        "  Use when the user wants multi-line\n"
        "  descriptions to load correctly.\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "multiline-skill", content)
    record = parse_skill_file(p)
    assert record is not None
    # block scalar preserves newline; .strip() removes trailing one
    assert "multi-line" in record.description
    assert "load correctly" in record.description


def test_root_yaml_is_a_list_not_dict(tmp_path, caplog):
    content = "---\n- one\n- two\n---\nbody\n"
    p = write_skill(tmp_path, "list-root", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is None


def test_yaml_only_a_comment(tmp_path, caplog):
    content = "---\n# just a comment, no fields\n---\nbody\n"
    p = write_skill(tmp_path, "comment-only", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    # safe_load on only-comments returns None → not dict → fallback fails → skip
    assert record is None


def test_binary_garbage_returns_none(tmp_path, caplog):
    """Non-UTF8 bytes are read with errors='replace' so the loader doesn't crash.
    Without valid frontmatter the file is skipped (return None) with a warning."""
    skill_dir = tmp_path / "binary-skill"
    skill_dir.mkdir()
    p = skill_dir / "SKILL.md"
    p.write_bytes(b"\xff\xfe\x00\x01\x02bad bytes here \x80\x81")
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is None


# ---------------------------------------------------------------------------
# 2. Field adversaries
# ---------------------------------------------------------------------------


def test_name_exactly_64_chars_no_length_warning(tmp_path, caplog):
    name = "a" * 64
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    p = skill_dir / "SKILL.md"
    p.write_text(
        f"---\nname: {name}\n"
        f"description: Use when the user wants 64-char names to be tolerated cleanly\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert record.name == name
    assert not any("exceeds 64" in r.message for r in caplog.records)


def test_name_65_chars_triggers_length_warning(tmp_path, caplog):
    name = "a" * 65
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    p = skill_dir / "SKILL.md"
    p.write_text(
        f"---\nname: {name}\n"
        f"description: Use when the user wants oversized names to log a warning loud\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert any("exceeds 64" in r.message for r in caplog.records)


def test_empty_name_falls_back_to_dir_name(tmp_path, caplog):
    content = (
        "---\nname: ''\n"
        "description: Use when the user supplies an empty name string for testing\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "dir-fallback-skill", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert record.name == "dir-fallback-skill"


def test_missing_name_field_falls_back_to_dir_name(tmp_path):
    content = (
        "---\n"
        "description: Use when the user omits the name field entirely from frontmatter\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "no-name-field", content)
    record = parse_skill_file(p)
    assert record is not None
    assert record.name == "no-name-field"


def test_name_with_weird_chars_loaded_with_warning(tmp_path, caplog):
    # Name doesn't match dir → warn but load
    content = (
        "---\n"
        "name: weird name/with slash 🎉\n"
        "description: Use when the user puts emoji and slashes into names for kicks\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "weird-dir", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert "🎉" in record.name
    assert any("doesn't match directory" in r.message for r in caplog.records)


def test_empty_description_skipped(tmp_path, caplog):
    content = "---\nname: x\ndescription: ''\n---\nbody\n"
    p = write_skill(tmp_path, "x", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is None


def test_whitespace_only_description_skipped(tmp_path, caplog):
    content = "---\nname: x\ndescription: '   '\n---\nbody\n"
    p = write_skill(tmp_path, "x", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is None


def test_description_29_chars_warns(tmp_path, caplog):
    desc = "use when " + "a" * 20  # len = 9 + 20 = 29
    assert len(desc) == 29
    content = f"---\nname: short-desc\ndescription: {desc}\n---\nbody\n"
    p = write_skill(tmp_path, "short-desc", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert any("too short" in r.message or "trigger phrase" in r.message
               for r in caplog.records)


def test_description_30_chars_with_trigger_no_warning(tmp_path, caplog):
    desc = "use when " + "a" * 21  # len = 30
    assert len(desc) == 30
    content = f"---\nname: just-right\ndescription: {desc}\n---\nbody\n"
    p = write_skill(tmp_path, "just-right", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    quality_warnings = [r for r in caplog.records if "trigger phrase" in r.message]
    assert quality_warnings == []


def test_description_long_but_no_trigger_warns(tmp_path, caplog):
    desc = "This describes something at length but lacks any cue word entirely"
    assert len(desc) >= 30
    content = f"---\nname: notrig\ndescription: {desc}\n---\nbody\n"
    p = write_skill(tmp_path, "notrig", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert any("trigger phrase" in r.message for r in caplog.records)


def test_trigger_phrase_case_insensitive(tmp_path, caplog):
    desc = "USE WHEN you need uppercase trigger phrase recognition to actually work"
    content = f"---\nname: upper\ndescription: {desc}\n---\nbody\n"
    p = write_skill(tmp_path, "upper", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    quality_warnings = [r for r in caplog.records if "trigger phrase" in r.message]
    assert quality_warnings == []


def test_allowed_tools_takes_precedence_over_tools(tmp_path):
    content = (
        "---\n"
        "name: precedence\n"
        "description: Use when the user defines both allowed-tools and tools fields\n"
        "allowed-tools:\n"
        "  - Bash(git status:*)\n"
        "  - Read\n"
        "tools:\n"
        "  - LegacyTool\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "precedence", content)
    record = parse_skill_file(p)
    assert record is not None
    assert record.allowed_tools == ["Bash(git status:*)", "Read"]
    assert "LegacyTool" not in record.allowed_tools


def test_allowed_tools_as_string_ignored_with_warning(tmp_path, caplog):
    content = (
        "---\n"
        "name: str-tools\n"
        "description: Use when the user accidentally writes allowed-tools as a string\n"
        "allowed-tools: Bash\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "str-tools", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert record.allowed_tools == []
    assert any("non-list" in r.message for r in caplog.records)


def test_mixed_dict_and_string_tools_one_coercion_warning(tmp_path, caplog):
    content = (
        "---\n"
        "name: mixed\n"
        "description: Use when the user mixes dict-style and string-style tool entries\n"
        "tools:\n"
        "  - Bash\n"
        "  - name: Read\n"
        "  - name: Write\n"
        "  - Grep\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "mixed", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert record.allowed_tools == ["Bash", "Read", "Write", "Grep"]
    coercion_warnings = [r for r in caplog.records if "legacy dict-style" in r.message]
    assert len(coercion_warnings) == 1


def test_dict_entry_without_name_dropped_silently(tmp_path, caplog):
    content = (
        "---\n"
        "name: noname-dict\n"
        "description: Use when the user gives dict-style entries that lack a name key\n"
        "tools:\n"
        "  - foo: bar\n"
        "  - Bash\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "noname-dict", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    # Dict with no 'name' is dropped (empty name); Bash retained
    assert record.allowed_tools == ["Bash"]
    # Critically: no coercion warning, because nothing was successfully coerced
    coercion_warnings = [r for r in caplog.records if "legacy dict-style" in r.message]
    assert coercion_warnings == []


def test_tools_value_is_dict_not_list(tmp_path, caplog):
    content = (
        "---\n"
        "name: dict-tools\n"
        "description: Use when the user provides a dict for tools instead of a list\n"
        "tools:\n"
        "  Bash: allowed\n"
        "  Read: yes\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "dict-tools", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    assert record.allowed_tools == []
    assert any("non-list" in r.message for r in caplog.records)


def test_tools_with_nulls_numbers_nested_lists(tmp_path, caplog):
    content = (
        "---\n"
        "name: weird-types\n"
        "description: Use when the user puts wild types in the tools list to test it\n"
        "tools:\n"
        "  - Bash\n"
        "  - null\n"
        "  - 42\n"
        "  - [nested, list]\n"
        "  - 3.14\n"
        "---\nbody\n"
    )
    p = write_skill(tmp_path, "weird-types", content)
    with caplog.at_level(logging.WARNING):
        record = parse_skill_file(p)
    assert record is not None
    # Only valid string entries are kept; nulls, numbers, nested lists are
    # dropped (not coerced to literal "None"/"42" etc) with one warning.
    assert record.allowed_tools == ["Bash"]
    drop_warnings = [r for r in caplog.records if "dropped" in r.message]
    assert len(drop_warnings) == 1
    assert "4" in drop_warnings[0].message  # 4 entries dropped: null, 42, list, 3.14


# ---------------------------------------------------------------------------
# 3. Discovery adversaries
# ---------------------------------------------------------------------------


def _valid_md(name: str) -> str:
    return (
        f"---\nname: {name}\n"
        f"description: Use when the user needs to test depth-limited discovery here\n"
        f"---\nbody\n"
    )


def test_skill_at_depth_4_included(tmp_path, isolated_home):
    # cwd/.claude/skills/ is the scan root (depth 0)
    # Then skills at deeper levels:
    # skills/a/b/c/d/SKILL.md → walked at depth 1,2,3,4 (entry == "d" found at depth 4)
    base = tmp_path / ".claude" / "skills"
    nested = base / "a" / "b" / "c" / "d"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(_valid_md("d"), encoding="utf-8")

    skills = discover_skills(tmp_path)
    assert "d" in skills


def test_skill_at_depth_5_excluded(tmp_path, isolated_home):
    """_MAX_DEPTH is enforced consistently: nesting beyond 4 levels under the
    scan root is not discovered."""
    base = tmp_path / ".claude" / "skills"
    nested = base / "a" / "b" / "c" / "d" / "e"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(_valid_md("e"), encoding="utf-8")

    skills = discover_skills(tmp_path)
    assert "e" not in skills


def test_collision_first_found_wins_logs_shadow(tmp_path, isolated_home, caplog):
    # Project-scope (.claude) is checked first; user-scope second.
    project_dir = tmp_path / ".claude" / "skills" / "dup"
    project_dir.mkdir(parents=True)
    (project_dir / "SKILL.md").write_text(_valid_md("dup"), encoding="utf-8")

    user_dir = isolated_home / ".claude" / "skills" / "dup"
    user_dir.mkdir(parents=True)
    (user_dir / "SKILL.md").write_text(_valid_md("dup"), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        skills = discover_skills(tmp_path)

    assert "dup" in skills
    # Project scope wins
    assert skills["dup"].scope == "project"
    assert any("shadowed" in r.message for r in caplog.records)


def test_unreadable_subdir_swallowed(tmp_path, isolated_home):
    """Unreadable sibling dirs (mode 0o000) no longer abort the whole scan;
    PermissionError from is_dir/is_file is caught per-entry."""
    if os.geteuid() == 0:
        pytest.skip("running as root, chmod 0o000 has no effect")
    base = tmp_path / ".claude" / "skills"
    base.mkdir(parents=True)
    good = base / "good"
    good.mkdir()
    (good / "SKILL.md").write_text(_valid_md("good"), encoding="utf-8")

    locked = base / "locked"
    locked.mkdir()
    os.chmod(locked, 0o000)
    try:
        skills = discover_skills(tmp_path)
        assert "good" in skills
    finally:
        os.chmod(locked, 0o755)


def test_symlink_loop_does_not_hang(tmp_path, isolated_home):
    base = tmp_path / ".claude" / "skills"
    base.mkdir(parents=True)
    real = base / "real"
    real.mkdir()
    (real / "SKILL.md").write_text(_valid_md("real"), encoding="utf-8")

    # Create a directory loop via symlink: base/loop -> base
    loop_link = base / "loop"
    try:
        loop_link.symlink_to(base, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported on this platform")

    # _MAX_DEPTH=4 should bound recursion; this must terminate.
    skills = discover_skills(tmp_path)
    assert "real" in skills


def test_empty_skills_directory(tmp_path, isolated_home):
    base = tmp_path / ".claude" / "skills"
    base.mkdir(parents=True)
    skills = discover_skills(tmp_path)
    assert skills == {}


def test_parent_dir_with_spaces_and_unicode(tmp_path, isolated_home):
    base = tmp_path / ".claude" / "skills"
    base.mkdir(parents=True)
    weird = base / "skill with spaces 中文 🚀"
    weird.mkdir()
    # Note: name in YAML must match dir or we get a warning.
    (weird / "SKILL.md").write_text(
        "---\n"
        "name: skill with spaces 中文 🚀\n"
        "description: Use when the user has unicode and spaces in directory names oh\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    skills = discover_skills(tmp_path)
    assert "skill with spaces 中文 🚀" in skills


def test_skip_dirs_not_traversed(tmp_path, isolated_home):
    """SKILL.md inside a SKIP_DIRS-named directory should be ignored."""
    base = tmp_path / ".claude" / "skills"
    base.mkdir(parents=True)

    # Create a node_modules folder containing a skill — it should be skipped
    skipped = base / "node_modules" / "evil"
    skipped.mkdir(parents=True)
    (skipped / "SKILL.md").write_text(_valid_md("evil"), encoding="utf-8")

    # And a normal sibling
    normal = base / "good"
    normal.mkdir()
    (normal / "SKILL.md").write_text(_valid_md("good"), encoding="utf-8")

    skills = discover_skills(tmp_path)
    assert "good" in skills
    assert "evil" not in skills


# ---------------------------------------------------------------------------
# 4. Manager adversaries
# ---------------------------------------------------------------------------


def _record(name: str, description: str, tmp_path: Path) -> SkillRecord:
    loc = tmp_path / name / "SKILL.md"
    loc.parent.mkdir(parents=True, exist_ok=True)
    loc.write_text("---\n---\nbody", encoding="utf-8")
    return SkillRecord(
        name=name,
        description=description,
        location=loc.resolve(),
        body="body",
        scope="project",
        allowed_tools=[],
    )


def test_catalog_xml_escapes_special_chars(tmp_path):
    """SkillManager.catalog_xml escapes <, >, & in name/description so that
    hostile or sloppy SKILL.md content cannot inject into the system prompt."""
    rec = _record(
        "weird-chars",
        "Use when foo <inject>&bar</inject> happens & things break unexpectedly",
        tmp_path,
    )
    mgr = SkillManager({rec.name: rec})
    xml = mgr.catalog_xml()
    assert "<inject>" not in xml
    assert "&lt;inject&gt;" in xml
    assert "&amp;bar" in xml
    assert xml.startswith("<available_skills>")
    assert xml.endswith("</available_skills>")


def test_catalog_xml_with_newlines_in_description(tmp_path):
    rec = _record("nl", "Line one\nLine two with \"quotes\"", tmp_path)
    mgr = SkillManager({rec.name: rec})
    xml = mgr.catalog_xml()
    assert "Line one\nLine two" in xml


def test_get_body_unknown_returns_none(tmp_path):
    mgr = SkillManager({})
    assert mgr.get_body("does-not-exist") is None


def test_catalog_xml_empty_manager_well_formed():
    mgr = SkillManager({})
    xml = mgr.catalog_xml()
    assert xml == "<available_skills>\n</available_skills>"


def test_description_with_control_characters(tmp_path):
    rec = _record("ctrl", "Use when desc has \x07bell\x08backspace\x1bescape chars", tmp_path)
    mgr = SkillManager({rec.name: rec})
    xml = mgr.catalog_xml()
    # Documenting passthrough: control chars survive, which would break XML parsers.
    assert "\x07" in xml

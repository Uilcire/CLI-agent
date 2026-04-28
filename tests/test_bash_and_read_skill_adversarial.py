"""
Adversarial tests for the new generic `bash` tool and the rebuilt `read_skill`.

These tests intentionally probe surprising shell semantics, security
boundaries, and integration-with-registry behavior. They use real subprocess
calls — `subprocess.run` is NOT mocked.

Run:
    uv run pytest tests/test_bash_and_read_skill_adversarial.py -v
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from agent.core.state import ConversationState
from agent.skills.loader import parse_skill_file
from agent.skills.manager import SkillManager
from agent.tools import registry
from agent.tools.bash import run_bash, _PROJECT_ROOT
from agent.tools.read_skill import read_skill

skip_on_win = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX-shell-only behavior"
)

# ---------------------------------------------------------------------------
# Skill fixture helpers
# ---------------------------------------------------------------------------

VALID_SKILL_MD = """\
---
name: pdf-processing
description: Use when the user needs to extract PDF text, fill forms, or merge files.
---

## When to use this skill
Body content with multiple lines.

## Steps
1. Step one
2. Step two
"""


def _make_skill(tmp_path: Path, name: str, content: str, extras: list[str] | None = None):
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    if extras:
        for fname in extras:
            (skill_dir / fname).write_text("# resource", encoding="utf-8")
    record = parse_skill_file(skill_dir / "SKILL.md", scope="project")
    assert record is not None
    return SkillManager({record.name: record}), ConversationState(), skill_dir


# ===========================================================================
# BASH — shell semantics / command injection surface
# ===========================================================================

class TestBashShellSemantics:
    @skip_on_win
    def test_chained_with_semicolon_runs_all(self):
        out = run_bash("echo first; echo second; echo third")
        assert "first" in out and "second" in out and "third" in out

    @skip_on_win
    def test_chained_with_and_short_circuits(self):
        # rc=0 chain: both should run
        out = run_bash("echo one && echo two")
        assert "one" in out and "two" in out

    @skip_on_win
    def test_or_short_circuits_after_failure(self):
        # `false || echo recovered` → rc=0, stdout = "recovered"
        out = run_bash("false || echo recovered")
        assert "recovered" in out
        assert not out.startswith("Error:")

    @skip_on_win
    def test_redirect_to_file(self, tmp_path):
        target = tmp_path / "out.txt"
        out = run_bash(f"echo redirected > {target}", cwd=str(tmp_path))
        # rc=0, no stdout
        assert out == "(no output)"
        assert target.read_text().strip() == "redirected"

    @skip_on_win
    def test_pipe_chain(self):
        out = run_bash("echo hi | tr h H")
        assert "Hi" in out

    @skip_on_win
    def test_command_substitution_dollar(self):
        out = run_bash('echo "value=$(echo nested)"')
        assert "value=nested" in out

    @skip_on_win
    def test_command_substitution_backticks(self):
        out = run_bash("echo `echo backtick`")
        assert "backtick" in out

    @skip_on_win
    def test_unicode_output(self):
        out = run_bash("echo 你好世界")
        assert "你好世界" in out

    @skip_on_win
    def test_embedded_newlines_in_command(self):
        # The `command` arg itself contains a newline — bash treats as separator
        out = run_bash("echo line1\necho line2")
        assert "line1" in out and "line2" in out


# ===========================================================================
# BASH — failure modes and output handling
# ===========================================================================

class TestBashFailureModes:
    def test_nonexistent_command(self):
        out = run_bash("thiscmddoesnotexist_xyz_42")
        assert out.startswith("Error: command exited with code")
        # stderr should be surfaced
        assert "stderr" in out

    @skip_on_win
    def test_stderr_on_success_is_surfaced(self):
        """rc=0 with empty stdout but non-empty stderr returns the stderr text
        so callers don't lose progress/warning output (pip/git/make patterns)."""
        out = run_bash("echo oops 1>&2")
        assert "oops" in out

    @skip_on_win
    def test_stdout_and_stderr_on_success_both_returned(self):
        """When both streams have content on rc=0, stdout comes first followed
        by a '--- stderr ---' section."""
        out = run_bash("echo first; echo second 1>&2")
        assert "first" in out
        assert "second" in out
        assert "--- stderr ---" in out

    @skip_on_win
    def test_stdout_and_stderr_with_nonzero_rc_both_captured(self):
        out = run_bash("echo to_stdout; echo to_stderr 1>&2; exit 7")
        assert "exited with code 7" in out
        assert "to_stdout" in out
        assert "to_stderr" in out
        assert "stdout:" in out
        assert "stderr:" in out

    @skip_on_win
    def test_empty_stdout_empty_stderr_nonzero_rc(self):
        out = run_bash("exit 9")
        assert "Error: command exited with code 9" in out
        # No phantom stdout: / stderr: blocks
        assert "stdout:" not in out
        assert "stderr:" not in out

    @skip_on_win
    def test_large_output_no_crash(self):
        # ~1MB of 'a' characters
        out = run_bash("python3 -c \"print('a' * 1000000)\"")
        assert len(out) >= 1_000_000
        assert out.startswith("a")

    def test_no_output_returns_placeholder(self):
        out = run_bash("true")
        assert out == "(no output)"

    def test_success_strips_trailing_newline(self):
        out = run_bash("printf hello")
        assert out == "hello"

        out2 = run_bash("echo hello")  # echo adds \n, should be rstripped
        assert out2 == "hello"


# ===========================================================================
# BASH — timeout
# ===========================================================================

class TestBashTimeout:
    def test_timeout_kills_long_command(self):
        out = run_bash("python3 -c 'import time; time.sleep(3)'", timeout=1)
        assert "timed out after 1s" in out

    def test_short_sleep_within_timeout(self):
        out = run_bash("python3 -c 'import time; time.sleep(0.2)'", timeout=5)
        assert not out.startswith("Error:")

    def test_default_timeout_is_60(self):
        import inspect
        sig = inspect.signature(run_bash)
        assert sig.parameters["timeout"].default == 60


# ===========================================================================
# BASH — cwd handling
# ===========================================================================

class TestBashCwd:
    def test_default_cwd_is_project_root(self):
        out = run_bash("pwd")
        assert out.strip() == str(_PROJECT_ROOT)

    def test_nonexistent_cwd_returns_error(self):
        out = run_bash("echo hi", cwd="/nonexistent/path/xyz_123")
        assert out.startswith("Error: cwd does not exist")

    def test_existing_tmp_cwd_runs(self, tmp_path):
        out = run_bash("pwd", cwd=str(tmp_path))
        # macOS may prefix /tmp with /private; check the basename matches
        assert Path(out.strip()).resolve() == tmp_path.resolve()

    def test_empty_string_cwd_falls_back_to_project_root(self):
        """cwd='' is treated like cwd=None and uses the project-root default,
        instead of silently running in the Python process's cwd."""
        out = run_bash("pwd", cwd="")
        assert Path(out.strip()).resolve() == _PROJECT_ROOT.resolve()

    def test_cwd_with_dotdot_resolves(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        # `<tmp>/sub/..` resolves to `<tmp>` — this IS allowed; no traversal guard.
        out = run_bash("pwd", cwd=f"{sub}/..")
        assert Path(out.strip()).resolve() == tmp_path.resolve()

    def test_cwd_is_a_file_returns_error(self, tmp_path):
        f = tmp_path / "a_file.txt"
        f.write_text("x")
        out = run_bash("echo hi", cwd=str(f))
        assert out.startswith("Error: cwd does not exist or is not a directory")

    def test_cwd_tilde_expansion(self):
        # ~ should expand to home; home exists, so command runs.
        out = run_bash("pwd", cwd="~")
        assert not out.startswith("Error:")
        assert out.strip() == str(Path.home())


# ===========================================================================
# BASH — logging
# ===========================================================================

class TestBashLogging:
    def test_command_is_debug_logged(self, caplog):
        """Commands log at DEBUG (not INFO) so default-level loggers don't
        capture potentially sensitive command strings."""
        with caplog.at_level(logging.DEBUG, logger="agent.tools.bash"):
            run_bash("echo logged")
        assert any(
            "echo logged" in r.getMessage() and r.levelname == "DEBUG"
            for r in caplog.records
        )

    def test_command_not_logged_at_info_level(self, caplog):
        """At INFO level, the bash command is NOT recorded — secrets passed in
        the command string won't leak to default log handlers."""
        with caplog.at_level(logging.INFO, logger="agent.tools.bash"):
            run_bash("echo TOKEN=sk-not-a-real-secret-deadbeef")
        leaked = [
            r for r in caplog.records
            if "sk-not-a-real-secret-deadbeef" in r.getMessage()
        ]
        assert not leaked


# ===========================================================================
# READ_SKILL — adversarial
# ===========================================================================

class TestReadSkillAdversarial:
    def test_unknown_skill_error_format(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "x", VALID_SKILL_MD)
        out = read_skill("nope-not-here", mgr, state)
        assert out == "Error: skill 'nope-not-here' not found."

    def test_unknown_skill_does_not_mutate_state(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "x", VALID_SKILL_MD)
        read_skill("nonexistent", mgr, state)
        assert state.activated_skills == set()

    def test_idempotent_double_call(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        first = read_skill("pdf-processing", mgr, state)
        second = read_skill("pdf-processing", mgr, state)
        assert first == second
        assert "already loaded" not in second.lower()
        assert "already activated" not in second.lower()

    def test_state_set_grows_then_idempotent(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        assert "pdf-processing" not in state.activated_skills
        read_skill("pdf-processing", mgr, state)
        assert state.activated_skills == {"pdf-processing"}
        read_skill("pdf-processing", mgr, state)
        assert state.activated_skills == {"pdf-processing"}  # no crash, no dup

    def test_no_allowed_tools_omits_block(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        out = read_skill("pdf-processing", mgr, state)
        assert "<allowed_tools>" not in out
        assert "</allowed_tools>" not in out

    def test_allowed_tools_with_special_chars(self, tmp_path):
        content = """\
---
name: deploy-skill
description: Use when the user wants to deploy services to production.
allowed-tools:
  - Bash
  - Read
  - "Bash(git status:*)"
---
Body.
"""
        mgr, state, _ = _make_skill(tmp_path, "deploy-skill", content)
        out = read_skill("deploy-skill", mgr, state)

        assert "<tool>Bash</tool>" in out
        assert "<tool>Read</tool>" in out
        assert "<tool>Bash(git status:*)</tool>" in out

    def test_resources_listed_sorted_excluding_skill_md(self, tmp_path):
        mgr, state, skill_dir = _make_skill(
            tmp_path, "pdf-processing", VALID_SKILL_MD,
            extras=["zebra.py", "alpha.md", "beta.txt"],
        )
        out = read_skill("pdf-processing", mgr, state)

        # SKILL.md should never be listed
        assert "<file>SKILL.md</file>" not in out

        # All extras listed
        assert "<file>alpha.md</file>" in out
        assert "<file>beta.txt</file>" in out
        assert "<file>zebra.py</file>" in out

        # Sorted: alpha < beta < zebra
        i_a = out.index("alpha.md")
        i_b = out.index("beta.txt")
        i_z = out.index("zebra.py")
        assert i_a < i_b < i_z

    def test_resources_block_omitted_when_only_skill_md(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        out = read_skill("pdf-processing", mgr, state)
        assert "<skill_resources>" not in out

    def test_resource_listing_graceful_on_missing_dir(self, tmp_path):
        """If the skill_dir is removed after parse, iterdir raises OSError →
        empty resource list, no crash."""
        mgr, state, skill_dir = _make_skill(
            tmp_path, "ephemeral", VALID_SKILL_MD.replace("pdf-processing", "ephemeral"),
            extras=["data.txt"],
        )
        # Wipe directory after parsing
        import shutil
        shutil.rmtree(skill_dir)

        out = read_skill("ephemeral", mgr, state)
        # No crash; envelope still returned, no resources section
        assert "<skill_content" in out
        assert "</skill_content>" in out
        assert "<skill_resources>" not in out

    def test_skill_body_with_xml_like_content_passthrough(self, tmp_path):
        """
        Skill bodies are inserted verbatim. If the body contains the literal
        string `</skill_content>`, the wrapper now contains TWO closing tags,
        which would confuse a naive XML parser downstream. Documented hazard
        — there's no escaping.
        """
        content = """\
---
name: tricky
description: Use when investigating XML escape edge cases in skills.
---

Body that contains </skill_content> literally — no escaping.
"""
        mgr, state, _ = _make_skill(tmp_path, "tricky", content)
        out = read_skill("tricky", mgr, state)
        # Two occurrences: one in body, one at end
        assert out.count("</skill_content>") == 2

    def test_empty_body_still_valid_envelope(self, tmp_path):
        content = (
            "---\nname: empty\n"
            "description: Use when testing envelopes with empty body content.\n---\n"
        )
        mgr, state, _ = _make_skill(tmp_path, "empty", content)
        out = read_skill("empty", mgr, state)
        assert out.startswith('<skill_content name="empty">')
        assert out.rstrip().endswith("</skill_content>")

    def test_very_long_body_not_truncated(self, tmp_path):
        long_body = "X" * 100_000
        content = (
            f"---\nname: huge\n"
            f"description: Use when testing huge skill bodies for truncation.\n---\n"
            f"{long_body}\n"
        )
        mgr, state, _ = _make_skill(tmp_path, "huge", content)
        out = read_skill("huge", mgr, state)
        assert long_body in out
        assert len(out) >= 100_000

    def test_skill_directory_path_is_absolute(self, tmp_path):
        mgr, state, skill_dir = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        out = read_skill("pdf-processing", mgr, state)
        # The skill_dir line should be an absolute path
        for line in out.splitlines():
            if line.startswith("Skill directory:"):
                p = line.split("Skill directory:", 1)[1].strip()
                assert Path(p).is_absolute()
                break
        else:
            pytest.fail("Skill directory line missing")


# ===========================================================================
# REGISTRY INTEGRATION
# ===========================================================================

class TestRegistryIntegration:
    def test_bash_tool_registered_with_correct_schema(self):
        # bash registers unconditionally — no skill init needed for this slot
        registry.init(SkillManager({}), ConversationState())
        tools = registry.get_tools()
        bash_specs = [t for t in tools if t["function"]["name"] == "bash"]
        assert len(bash_specs) == 1
        spec = bash_specs[0]
        params = spec["function"]["parameters"]
        assert params["type"] == "object"
        assert "command" in params["properties"]
        assert "cwd" in params["properties"]
        assert "timeout" in params["properties"]
        assert params["required"] == ["command"]
        assert params["properties"]["timeout"].get("default") == 60

    def test_read_skill_absent_when_no_skills(self):
        registry.init(SkillManager({}), ConversationState())
        tools = registry.get_tools()
        names = [t["function"]["name"] for t in tools]
        assert "read_skill" not in names
        assert "bash" in names  # bash still present

    def test_read_skill_present_when_skills_exist(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        registry.init(mgr, state)
        tools = registry.get_tools()
        names = [t["function"]["name"] for t in tools]
        assert "read_skill" in names
        rs = next(t for t in tools if t["function"]["name"] == "read_skill")
        # name enum should contain the skill
        enum = rs["function"]["parameters"]["properties"]["name"].get("enum")
        assert enum == ["pdf-processing"]

    def test_dispatch_bash_via_execute(self):
        registry.init(SkillManager({}), ConversationState())
        out = registry.execute("bash", {"command": "echo dispatched"})
        assert "dispatched" in out

    def test_dispatch_bash_with_cwd_and_timeout(self, tmp_path):
        registry.init(SkillManager({}), ConversationState())
        out = registry.execute(
            "bash",
            {"command": "pwd", "cwd": str(tmp_path), "timeout": 5},
        )
        assert Path(out.strip()).resolve() == tmp_path.resolve()

    def test_dispatch_bash_timeout_string_coerced(self):
        """registry.execute does int(args.get("timeout", 60)) — verify
        a string timeout is coerced rather than crashing."""
        registry.init(SkillManager({}), ConversationState())
        out = registry.execute(
            "bash",
            {"command": "python3 -c 'import time; time.sleep(2)'", "timeout": "1"},
        )
        assert "timed out after 1s" in out

    def test_dispatch_read_skill_routes_correctly(self, tmp_path):
        mgr, state, _ = _make_skill(tmp_path, "pdf-processing", VALID_SKILL_MD)
        registry.init(mgr, state)
        out = registry.execute("read_skill", {"name": "pdf-processing"})
        assert "<skill_content" in out
        assert "pdf-processing" in state.activated_skills

    def test_dispatch_read_skill_when_uninitialized(self):
        # Force the not-initialized branch.
        registry._skill_manager = None
        registry._state = None
        out = registry.execute("read_skill", {"name": "anything"})
        assert "Error: skill system not initialized." == out

    def test_dispatch_bash_missing_command_arg(self):
        registry.init(SkillManager({}), ConversationState())
        out = registry.execute("bash", {})
        # KeyError caught by registry → "Error: ..."
        assert out.startswith("Error:")

    def test_dispatch_unknown_tool(self):
        registry.init(SkillManager({}), ConversationState())
        out = registry.execute("totally_made_up", {})
        assert "Unknown tool" in out

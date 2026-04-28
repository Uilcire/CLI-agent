"""Generic bash tool: execute a shell command and return its output."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent.logger import get_logger

log = get_logger(__name__)


# Project root: src/agent/tools/bash.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_bash(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    """
    Execute *command* via the system shell and return the result as a string.

    Shell access is intentional: skill bodies need pipes, redirects, env-var
    expansion, and arbitrary CLI invocations. Caller is responsible for
    producing valid shell syntax — no quoting/escaping is performed here.

    Args:
        command: shell command (passed to subprocess with shell=True).
        cwd: working directory. Defaults to the project root.
        timeout: seconds before the command is killed. Default 60.

    Returns:
        On rc 0: stdout (or "(no output)" if empty).
        Otherwise: a formatted error string with rc, stdout, stderr.
    """
    if not cwd:
        run_cwd = _PROJECT_ROOT
    else:
        run_cwd = Path(cwd).expanduser()
        if not run_cwd.exists() or not run_cwd.is_dir():
            return f"Error: cwd does not exist or is not a directory: {cwd}"

    log.debug("bash: %s (cwd=%s, timeout=%ss)", command, run_cwd, timeout)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(run_cwd),
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except OSError as e:
        return f"Error: failed to execute command: {e}"

    if result.returncode == 0:
        out = result.stdout.rstrip("\n")
        err = result.stderr.rstrip("\n")
        if out and err:
            return f"{out}\n--- stderr ---\n{err}"
        return out or err or "(no output)"

    parts = [f"Error: command exited with code {result.returncode}"]
    if result.stdout.strip():
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n".join(parts)

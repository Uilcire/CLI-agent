"""Integration tests for delete tools and permission gates."""

import pytest
from pathlib import Path

from agent.permissions import (
    clear_delete_permissions,
    grant_delete_permission,
    has_delete_permission,
)
from agent.tools.registry import execute


@pytest.fixture(autouse=True)
def clear_permissions():
    """Clear granted paths before each test for isolation."""
    clear_delete_permissions()
    yield


@pytest.fixture
def temp_files(tmp_path):
    """Create temp dir with files for delete tests."""
    (tmp_path / "f1.txt").write_text("x")
    (tmp_path / "f2.txt").write_text("y")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f3.txt").write_text("z")
    return tmp_path


def test_non_tty_defaults_to_cancel(temp_files):
    """When stdin is not a TTY, delete defaults to cancel."""
    f = temp_files / "f1.txt"
    result = execute("delete_file", {"path": str(f)})
    assert result == "Delete cancelled by user."
    assert f.exists()


def test_grant_then_delete_skips_prompt(temp_files):
    """When path is granted, delete proceeds without confirmation."""
    grant_delete_permission(str(temp_files))
    f = temp_files / "f1.txt"
    result = execute("delete_file", {"path": str(f)})
    assert "Deleted" in result
    assert not f.exists()


def test_child_path_covered_by_parent_grant(temp_files):
    """Deleting file inside granted dir skips prompt."""
    grant_delete_permission(str(temp_files))
    f = temp_files / "sub" / "f3.txt"
    result = execute("delete_file", {"path": str(f)})
    assert "Deleted" in result
    assert not f.exists()


def test_delete_dir_with_grant(temp_files):
    """delete_dir removes directory when granted."""
    grant_delete_permission(str(temp_files))
    result = execute("delete_dir", {"path": str(temp_files)})
    assert "Deleted" in result
    assert not temp_files.exists()


def test_delete_nonexistent_returns_error():
    """delete_dir on non-existent path returns error."""
    result = execute("delete_dir", {"path": "/nonexistent/path"})
    assert "Error" in result


def test_delete_file_on_directory_returns_error(temp_files):
    """delete_file on a directory returns error."""
    result = execute("delete_file", {"path": str(temp_files)})
    assert "Error" in result
    assert "not a file" in result


def test_delete_dir_on_file_returns_error(temp_files):
    """delete_dir on a file returns error."""
    f = temp_files / "f1.txt"
    f.write_text("x")
    result = execute("delete_dir", {"path": str(f)})
    assert "Error" in result
    assert "not a directory" in result


def test_check_permissions_tool(temp_files):
    """check_permissions lists grants and checks specific path."""
    result = execute("check_permissions", {})
    assert "No delete permissions" in result
    result = execute("check_permissions", {"path": str(temp_files)})
    assert "does not have" in result
    grant_delete_permission(str(temp_files))
    result = execute("check_permissions", {})
    assert "Granted delete paths" in result and str(temp_files) in result
    result = execute("check_permissions", {"path": str(temp_files / "f1.txt")})
    assert "has delete permission" in result


def test_has_delete_permission():
    """Permission check works for path and descendants."""
    from agent.permissions import clear_delete_permissions

    clear_delete_permissions()
    grant_delete_permission("/tmp/foo")
    assert has_delete_permission("/tmp/foo")
    assert has_delete_permission("/tmp/foo/bar")
    assert not has_delete_permission("/tmp/other")

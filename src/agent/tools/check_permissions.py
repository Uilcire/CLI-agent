"""Check current delete permissions."""

from agent.permissions import get_granted_delete_paths, has_delete_permission


def check_permissions(path: str | None = None) -> str:
    """
    Check delete permissions.
    With no path: list all granted paths.
    With path: report whether that path has delete permission.

    Args:
        path: Optional path to check. If omitted, lists all granted paths.

    Returns:
        Human-readable permission status.
    """
    if path is None:
        granted = get_granted_delete_paths()
        if not granted:
            return "No delete permissions granted this session."
        return "Granted delete paths:\n" + "\n".join(f"  - {p}" for p in granted)
    if has_delete_permission(path):
        return f"Path {path!r} has delete permission (granted or under a granted path)."
    return f"Path {path!r} does not have delete permission. A confirmation dialog will pop up when delete_file or delete_dir is called."

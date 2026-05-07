"""Migrate ~/assistant-memory/projects/ → life/_archive_from_projects.md.

Phase A scope refactor: the cwd-keyed `projects/` scope is replaced by
`life/`, `threads/`, and `events/`. This script archives the old project
files into a single dump under `life/`, then renames `projects/` to
`projects.legacy/` so nothing is silently deleted.

Idempotent: if `projects.legacy/` already exists, the script is a no-op.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _memory_root() -> Path:
    raw = os.environ.get("ASSISTANT_MEMORY_DIR") or "~/assistant-memory"
    return Path(raw).expanduser().resolve()


def main() -> int:
    root = _memory_root()
    projects_dir = root / "projects"
    legacy_dir = root / "projects.legacy"
    life_dir = root / "life"
    archive_path = life_dir / "_archive_from_projects.md"

    if legacy_dir.exists():
        print(f"[skip] {legacy_dir} already exists; migration already ran.")
        return 0

    if not projects_dir.exists():
        print(f"[skip] {projects_dir} does not exist; nothing to migrate.")
        return 0

    files = sorted(p for p in projects_dir.rglob("*.md") if p.is_file())
    if not files:
        # Still rename the empty dir so future runs are idempotent.
        projects_dir.rename(legacy_dir)
        print(f"[ok] {projects_dir} was empty; renamed to {legacy_dir}.")
        return 0

    life_dir.mkdir(parents=True, exist_ok=True)

    parts: list[str] = [
        "# Archived project files (from former `projects/` scope)\n",
        "These were migrated by `scripts/migrate_personal_scopes.py` during the\n"
        "Phase A scope refactor. Review and re-file into `life/`, `threads/`,\n"
        "or `events/` as appropriate, then delete this file.\n",
    ]
    for path in files:
        rel = path.relative_to(projects_dir)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[warn] cannot read {path}: {exc}", file=sys.stderr)
            continue
        parts.append(f"\n=== {rel} ===\n\n{text.rstrip()}\n")

    archive_path.write_text("\n".join(parts), encoding="utf-8")
    projects_dir.rename(legacy_dir)

    print(f"[ok] archived {len(files)} project file(s) → {archive_path}")
    print(f"[ok] renamed {projects_dir} → {legacy_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

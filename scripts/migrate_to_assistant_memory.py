"""One-shot migration: old JSON memory -> new markdown assistant memory."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent.assistant_memory.store import AssistantMemoryStore
from agent.memory.models import Personality, Project, SessionDigest


@dataclass
class MigrationSummary:
    personality_migrated: bool = False
    projects: list[str] = field(default_factory=list)
    digests: int = 0
    log_files: set[str] = field(default_factory=set)
    archived_to: str | None = None
    dry_run: bool = False
    dst: str = ""


def _has_existing_content(dst: Path) -> bool:
    if not dst.exists():
        return False
    for path in dst.rglob("*.md"):
        if path.is_file():
            return True
    return False


def _bucket_date(timestamp: str) -> tuple[str, str]:
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m"), dt.strftime("%Y-%m-%d")


def _project_body(p: Project) -> str:
    caps = "\n".join(f"- {c}" for c in p.capabilities) if p.capabilities else "(none)"
    learnings = p.learnings.strip() if p.learnings else "(none)"
    return (
        f"# {p.project_id}\n\n"
        f"## Description\n{p.description}\n\n"
        f"## Capabilities\n{caps}\n\n"
        f"## Learnings\n{learnings}\n"
    )


def _project_meta(p: Project) -> dict:
    return {
        "project_id": p.project_id,
        "cwd": p.cwd,
        "status": p.status,
        "tags": list(p.tags),
        "capabilities": list(p.capabilities),
        "last_summarized_session": p.last_summarized_session or "",
    }


def _digest_section(d: SessionDigest) -> str:
    caps = ", ".join(d.capabilities) if d.capabilities else "(none)"
    learnings = d.learnings.strip() if d.learnings else "(none)"
    section = (
        f"## Session {d.session_id} ({d.project_id})\n"
        f"{d.summary}\n\n"
        f"**Capabilities:** {caps}\n"
        f"**Learnings:** {learnings}\n"
    )
    if d.fictional_backstory.strip():
        section += f"\n{d.fictional_backstory.strip()}\n"
    return section


def _projects_manifest(projects: list[Project]) -> str:
    lines = ["# Projects Manifest", ""]
    for p in sorted(projects, key=lambda x: x.project_id):
        tags = ", ".join(p.tags) if p.tags else "-"
        cwd = p.cwd or "-"
        lines.append(
            f"- **{p.project_id}.md** | {p.status} | {p.description} | cwd:{cwd} | tags: {tags}"
        )
    return "\n".join(lines) + "\n"


def _empty_manifest(title: str) -> str:
    return f"# {title} Manifest\n"


def _build_index(summary: MigrationSummary) -> str:
    return (
        "---\n"
        "user_summary: \"\"\n"
        f"last_rebuilt: {datetime.now().strftime('%Y-%m-%d')}\n"
        "---\n\n"
        "# Memory Index\n\n"
        "## Scopes\n"
        "- **identity/** — Who I am + agent's own soul\n"
        "- **people/** — 0 people tracked\n"
        "- **preferences/** — 0 preference areas\n"
        f"- **projects/** — {len(summary.projects)} migrated: "
        f"{', '.join(summary.projects) if summary.projects else '(none)'}\n"
        "- **context/current.md** — This week's state (always read)\n"
        f"- **log/** — {len(summary.log_files)} day file(s) across "
        f"{len({d[:7] for d in summary.log_files})} month(s)\n"
    )


def migrate(src: Path, dst: Path, *, dry_run: bool, archive: bool, force: bool) -> MigrationSummary:
    summary = MigrationSummary(dry_run=dry_run, dst=str(dst))

    if not src.exists():
        raise FileNotFoundError(f"source dir does not exist: {src}")

    if _has_existing_content(dst) and not force:
        raise RuntimeError(
            f"destination already has files: {dst}. Pass --force to override."
        )

    if dry_run:
        store = None
    else:
        store = AssistantMemoryStore(dst)

    personality_path = src / "personality.json"
    if personality_path.exists():
        p = Personality.model_validate_json(personality_path.read_text())
        summary.personality_migrated = True
        if store is not None:
            store.write_file(
                "identity/agent.md",
                {"name": "agent", "type": "identity", "immutable_core": p.immutable_core},
                p.soul,
            )

    projects: list[Project] = []
    projects_dir = src / "projects"
    if projects_dir.is_dir():
        for path in sorted(projects_dir.glob("*.json")):
            proj = Project.model_validate_json(path.read_text())
            projects.append(proj)
            summary.projects.append(proj.project_id)
            if store is not None:
                store.write_file(
                    f"projects/{proj.project_id}.md",
                    _project_meta(proj),
                    _project_body(proj),
                )

    digests_by_day: dict[str, list[str]] = {}
    digests_dir = src / "digests"
    if digests_dir.is_dir():
        digests: list[SessionDigest] = []
        for path in sorted(digests_dir.glob("*.json")):
            d = SessionDigest.model_validate_json(path.read_text())
            digests.append(d)
        digests.sort(key=lambda x: x.timestamp)
        for d in digests:
            month, day = _bucket_date(d.timestamp)
            rel = f"log/{month}/{day}.md"
            digests_by_day.setdefault(rel, []).append(_digest_section(d))
            summary.digests += 1
            summary.log_files.add(day)

        if store is not None:
            for rel, sections in digests_by_day.items():
                existing_meta, existing_body = store.read_file(rel)
                header = existing_body if existing_body else f"# {Path(rel).stem}\n\n"
                body = header.rstrip() + "\n\n" + "\n".join(sections)
                store.write_file(rel, existing_meta, body)

    if store is not None:
        if not (dst / "identity" / "me.md").exists():
            store.write_file(
                "identity/me.md",
                {"name": "user", "type": "identity"},
                "",
            )
        if not (dst / "context" / "current.md").exists():
            store.write_file("context/current.md", {}, "")

        store.write_manifest("people", _empty_manifest("People"))
        store.write_manifest("preferences", _empty_manifest("Preferences"))
        store.write_manifest("projects", _projects_manifest(projects))
        store.write_manifest("log", _empty_manifest("Log"))

        if not (dst / "_index.md").exists():
            store.write_index(_build_index(summary))

    if archive and not dry_run:
        legacy = Path(f"{src}.legacy")
        if legacy.exists():
            raise RuntimeError(f"archive target already exists: {legacy}")
        os.rename(src, legacy)
        summary.archived_to = str(legacy)

    return summary


def _print_summary(summary: MigrationSummary) -> None:
    print(f"Destination: {summary.dst}")
    print(f"Dry run: {summary.dry_run}")
    print(f"Personality migrated: {summary.personality_migrated}")
    print(f"Projects migrated ({len(summary.projects)}): {', '.join(summary.projects) or '(none)'}")
    print(f"Digests migrated: {summary.digests} across {len(summary.log_files)} day file(s)")
    if summary.archived_to:
        print(f"Archived old dir to: {summary.archived_to}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_to_assistant_memory",
        description="Migrate old JSON memory to new markdown assistant memory.",
    )
    parser.add_argument("--src", default="./agent-memory", help="old memory dir")
    parser.add_argument("--dst", default="~/assistant-memory", help="new memory dir")
    parser.add_argument("--dry-run", action="store_true", help="print plan, do not write")
    parser.add_argument(
        "--archive",
        dest="archive",
        action="store_true",
        default=True,
        help="rename old dir to .legacy after success (default)",
    )
    parser.add_argument(
        "--no-archive", dest="archive", action="store_false", help="do not archive old dir"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite even if dst already has content"
    )

    args = parser.parse_args(argv)

    src = Path(args.src).expanduser().resolve()
    dst = Path(args.dst).expanduser().resolve()

    try:
        summary = migrate(
            src, dst, dry_run=args.dry_run, archive=args.archive, force=args.force
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

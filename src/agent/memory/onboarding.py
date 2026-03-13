"""Project onboarding: classify with LLM and seed from similar past projects."""

import hashlib
import json
import os
import re
import uuid

from agent.memory.models import Project
from agent.memory.prompts import (
    ONBOARDING_SYSTEM,
    ONBOARDING_USER,
    PROJECT_DETECT_SYSTEM,
    PROJECT_DETECT_USER,
)


def cwd_project_id(cwd: str) -> str:
    """Stable 12-char project ID derived from absolute directory path."""
    abs_cwd = os.path.abspath(cwd)
    return hashlib.sha256(abs_cwd.encode()).hexdigest()[:12]


def scan_cwd(cwd: str) -> dict:
    """Scan cwd and return dir_name, file_listing, readme_snippet."""
    abs_cwd = os.path.abspath(cwd)
    dir_name = os.path.basename(abs_cwd)

    entries = sorted(os.listdir(cwd))
    visible = [e for e in entries if not e.startswith(".")]
    if len(visible) > 20:
        file_listing = ", ".join(visible[:20]) + "... (and more)"
    else:
        file_listing = ", ".join(visible)

    readme_candidates = ["README.md", "readme.md", "README.rst", "README.txt"]
    readme_snippet = "No README found."
    for name in readme_candidates:
        path = os.path.join(cwd, name)
        if os.path.isfile(path):
            content = ""
            try:
                content = open(path).read(500)
            except OSError:
                pass
            readme_snippet = " ".join(content.split())
            break

    return {
        "dir_name": dir_name,
        "file_listing": file_listing,
        "readme_snippet": readme_snippet,
    }


def _find_similar(
    new_tags: list[str], all_projects: list[Project], top_k: int = 3
) -> list[Project]:
    """Find projects with overlapping tags. Returns up to top_k, sorted by overlap."""
    new_set = set(new_tags)
    scored = [(p, len(new_set & set(p.tags))) for p in all_projects]
    nonzero = [(p, s) for p, s in scored if s > 0]
    sorted_projs = sorted(nonzero, key=lambda x: x[1], reverse=True)
    return [p for p, _ in sorted_projs[:top_k]]


def detect_and_onboard(
    cwd: str,
    store: "LocalMemoryStore",
    llm: "LLMClient",
    print_fn=print,
) -> Project:
    """Run filesystem-based detection and create project. Seeds from similar projects."""
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from agent.memory.llm import LLMClient
        from agent.memory.store import LocalMemoryStore

    print_fn("Scanning project directory...")
    scan = scan_cwd(cwd)
    user_msg = (
        PROJECT_DETECT_USER.replace("{dir_name}", scan["dir_name"])
        .replace("{file_listing}", scan["file_listing"])
        .replace("{readme_snippet}", scan["readme_snippet"])
    )
    print_fn("Classifying project with AI...")
    response = llm.complete(system=PROJECT_DETECT_SYSTEM, user=user_msg)

    parsed: dict | None = None
    for attempt in range(2):
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                break
            except json.JSONDecodeError:
                pass
        if attempt < 1:
            response = llm.complete(system=PROJECT_DETECT_SYSTEM, user=user_msg)

    if parsed is None:
        parsed = {
            "description": f"Project in {scan['dir_name']}",
            "suggested_tags": [],
            "suggested_capabilities": [],
        }

    description = parsed.get("description", f"Project in {scan['dir_name']}")
    if isinstance(description, str):
        pass
    else:
        description = str(description)
    tags = parsed.get("suggested_tags", [])
    if not isinstance(tags, list):
        tags = []
    capabilities = parsed.get("suggested_capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []

    similar = _find_similar(tags, store.list_projects())
    if similar:
        print_fn(f"Similar projects found: {', '.join(p.description for p in similar)}")
        caps_from_similar = [c for p in similar for c in p.capabilities]
        capabilities = list(dict.fromkeys(capabilities + caps_from_similar))
    else:
        print_fn("No similar projects found.")

    print_fn(f"Creating project: {description}")
    print_fn(f"  Tags: {', '.join(tags) or 'none'}")
    print_fn(f"  Capabilities: {', '.join(capabilities) or 'none'}")

    pid = cwd_project_id(cwd)
    project = Project(
        project_id=pid,
        description=description,
        status="active",
        tags=tags,
        capabilities=capabilities,
        cwd=os.path.abspath(cwd),
    )
    store.save_project(project)
    return project


def onboard_project(
    description: str,
    store: "LocalMemoryStore",
    llm: "LLMClient",
    print_fn=print,
) -> Project:
    """Create a new project via LLM classification. Seeds tags/capabilities from similar projects."""
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from agent.memory.llm import LLMClient
        from agent.memory.store import LocalMemoryStore

    # Step 1: call LLM first to get normalized tags from the description.
    user_msg = ONBOARDING_USER.replace("{description}", description).replace(
        "{existing_projects}", "No existing projects found."
    )
    response = llm.complete(system=ONBOARDING_SYSTEM, user=user_msg)
    parsed: dict | None = None
    for attempt in range(2):
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                break
            except json.JSONDecodeError:
                pass
        if attempt < 1:
            response = llm.complete(system=ONBOARDING_SYSTEM, user=user_msg)

    if parsed is None:
        tags, capabilities = [], []
    else:
        raw_tags = parsed.get("suggested_tags", [])
        raw_caps = parsed.get("relevant_capabilities", [])
        tags = raw_tags if isinstance(raw_tags, list) else []
        capabilities = raw_caps if isinstance(raw_caps, list) else []

    # Step 2: use real LLM-derived tags to find similar projects.
    similar = _find_similar(tags, store.list_projects())
    if similar:
        print_fn(f"Similar projects found: {', '.join(p.description for p in similar)}")
        caps_from_similar = [c for p in similar for c in p.capabilities]
        capabilities = list(dict.fromkeys(capabilities + caps_from_similar))
    else:
        print_fn("No similar projects found.")

    project_id = uuid.uuid4().hex[:8]
    project = Project(
        project_id=project_id,
        description=description,
        status="active",
        tags=tags,
        capabilities=capabilities,
        cwd="",
    )
    store.save_project(project)
    return project

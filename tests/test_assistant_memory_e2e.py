"""End-to-end retrieval validation for the assistant memory system.

Builds a realistic seed memory tree for the spec's example user (Eric) and
exercises the two-stage retrieval pipeline against the 10 validation queries
from the design doc.

LLM calls are replaced with a "smart mock" that parses the prompts and selects
scopes/files by keyword matching against the manifests and index. If a query
fails, that's a signal the manifests/hooks aren't rich enough — adjust the seed,
not the test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.assistant_memory.manager import AssistantMemoryManager
from agent.assistant_memory.retrieval import RetrievalPipeline
from agent.assistant_memory.store import AssistantMemoryStore


# ---------------------------------------------------------------------------
# Seed data — Eric, CS student / ByteDance intern in Singapore
# ---------------------------------------------------------------------------


def _seed_memory(root: Path) -> AssistantMemoryStore:
    store = AssistantMemoryStore(root)

    # _index.md
    store.write_index(
        "---\n"
        'user_summary: "Eric — CS student, ByteDance intern in Singapore researching AI agents."\n'
        "last_rebuilt: 2026-04-29\n"
        "---\n\n"
        "# Memory Index\n\n"
        "## Scopes\n"
        "- **identity/** — Who Eric is + agent's own soul\n"
        "- **people/** — 4 people tracked: alex, mom, jamie, sam\n"
        "- **preferences/** — 5 areas: food, coffee, reading, gifts, travel\n"
        "- **projects/** — 3 active: cli-agent, memact-research, code-llm-doc\n"
        "- **context/current.md** — This week's state (always read)\n"
        "- **log/** — Event history; monthly summaries available (2026-03, 2026-04)\n"
    )

    # identity/
    store.write_file(
        "identity/agent.md",
        {
            "immutable_core": (
                "Be genuinely helpful, not performative. Have opinions. "
                "Disagree when it matters. Private things stay private."
            ),
        },
        "# Agent Soul\n\n"
        "I am Eric's personal assistant. I prefer concision, value engineering "
        "rigor, and act with care on external systems.\n",
    )
    store.write_file(
        "identity/me.md",
        {
            "name": "Eric",
            "role": "CS student / ByteDance intern",
            "location": "Singapore",
            "interests": ["AI agents", "RL", "systems"],
        },
        "# Eric\n\nCS student, currently interning at ByteDance Singapore on AI agents.\n",
    )
    store.write_manifest(
        "identity",
        "# Identity Manifest\n\n"
        "- **me.md**     | Eric — CS student, ByteDance intern Singapore, AI agents focus\n"
        "- **agent.md**  | Agent's own soul + immutable_core values\n",
    )

    # people/
    store.write_file(
        "people/alex.md",
        {
            "name": "alex",
            "relation": "girlfriend",
            "since": 2024,
            "location": "SF",
            "birthday": "1999-11-12",
            "last_updated": "2026-04-20",
        },
        "# Alex\n\n"
        "Girlfriend since 2024. Lives in SF, EM at Stripe (since Apr 2026). "
        "Allergic to shellfish. Wants to go to Kyoto in fall 2026 — mentioned "
        "this on a call last week. Birthday Nov 12.\n",
    )
    store.write_file(
        "people/mom.md",
        {
            "name": "mom",
            "relation": "mother",
            "location": "Shanghai",
            "last_updated": "2026-04-15",
        },
        "# Mom\n\n"
        "Retired teacher in Shanghai. Recovering from knee surgery (Apr 2026). "
        "Weekly calls. Likes practical gifts — warm slippers, tea sets. "
        "Avoid anything bulky to ship.\n",
    )
    store.write_file(
        "people/jamie.md",
        {
            "name": "jamie",
            "relation": "best friend",
            "location": "Singapore",
            "last_updated": "2026-04-10",
        },
        "# Jamie\n\n"
        "Best friend from undergrad, also in Singapore. Works at GovTech. "
        "Recently went through a tough breakup (Mar 2026). Checking in monthly.\n",
    )
    store.write_file(
        "people/sam.md",
        {
            "name": "sam",
            "relation": "colleague",
            "location": "Singapore",
            "last_updated": "2026-04-22",
        },
        "# Sam\n\n"
        "Colleague at ByteDance Singapore. Vegetarian. Loves Sichuan food and "
        "natural wine. Visiting from SF next month — wants restaurant recs.\n",
    )
    store.write_manifest(
        "people",
        "# People Manifest\n"
        "Last rebuilt: 2026-04-29\n\n"
        "- **alex.md**  | Girlfriend, since 2024 | SF | EM at Stripe (Apr 2026) | "
        "allergic to shellfish | wants Kyoto trip fall 2026 | birthday Nov 12\n"
        "- **mom.md**   | Mother | Shanghai | retired teacher | "
        "recovering from knee surgery (Apr 2026) | weekly calls | "
        "likes practical gifts\n"
        "- **jamie.md** | Best friend | Singapore | GovTech engineer | "
        "tough breakup Mar 2026 | monthly check-ins\n"
        "- **sam.md**   | Colleague at ByteDance | Singapore | vegetarian | "
        "loves Sichuan + natural wine | visiting from SF next month, "
        "wants restaurant recommendations\n",
    )

    # preferences/
    store.write_file(
        "preferences/food.md",
        {"topic": "food"},
        "# Food\n\nNo allergies. Loves spicy (Sichuan, Thai). Dislikes overly "
        "sweet desserts. Open to trying anything once. Favorite Singapore "
        "restaurants: Burnt Ends, Candlenut, Maxwell hawker stalls.\n",
    )
    store.write_file(
        "preferences/coffee.md",
        {"topic": "coffee"},
        "# Coffee\n\nDaily V60 pour-over at home. Prefers light-roast Ethiopian "
        "beans (currently from Nylon Coffee Roasters). Espresso when out — "
        "flat white, oat milk. No sugar.\n",
    )
    store.write_file(
        "preferences/reading.md",
        {"topic": "reading"},
        "# Reading\n\nFavors AI / systems papers and long-form essays. Currently "
        "working through MemAct, Voyager, and SWE-agent papers. Likes Karpathy "
        "and Simon Willison blogs.\n",
    )
    store.write_file(
        "preferences/gifts.md",
        {"topic": "gifts"},
        "# Gifts\n\nBudget ~$100 default, more for family. Prefers thoughtful + "
        "practical over flashy. For mom: small comforts (slippers, tea). For "
        "Alex: experiences over objects. Avoid generic gift cards.\n",
    )
    store.write_file(
        "preferences/travel.md",
        {"topic": "travel"},
        "# Travel\n\nPrefers boutique hotels over chains. Packs light — one "
        "carry-on. Likes walking-heavy itineraries. Saving Kyoto and Lisbon "
        "for 2026.\n",
    )
    store.write_manifest(
        "preferences",
        "# Preferences Manifest\n\n"
        "- **food.md**    | dietary restrictions, cuisines liked, favorite "
        "restaurants and recommendations\n"
        "- **coffee.md**  | brewing setup, beans, drink preferences "
        "(V60, Ethiopian light-roast, flat white)\n"
        "- **reading.md** | genres, authors, current reading list "
        "(papers, essays)\n"
        "- **gifts.md**   | gift-giving habits, budget norms, what to give "
        "family vs friends vs partner\n"
        "- **travel.md**  | travel style, hotel preferences, packing habits, "
        "destinations on the wishlist\n",
    )

    # projects/
    store.write_file(
        "projects/cli-agent.md",
        {
            "project_id": "cli-agent",
            "cwd": "/Users/bytedance/Projects/CLI-agent",
            "status": "active",
            "tags": ["python", "agents"],
            "capabilities": ["tool-use", "react-loop"],
            "last_summarized_session": "2026-04-28",
        },
        "# CLI Agent\n\n## Description\n\nA CLI agent built from scratch in "
        "Python, à la Claude Code.\n\n## Learnings\n\n- ReAct loops + permission "
        "tiers + compaction.\n",
    )
    store.write_file(
        "projects/memact-research.md",
        {
            "project_id": "memact-research",
            "cwd": "",
            "status": "active",
            "tags": ["research", "papers"],
            "capabilities": [],
            "last_summarized_session": "2026-04-25",
        },
        "# MemAct Research\n\n## Description\n\nDeep-dive on the MemAct paper "
        "(memory-as-action for LLM agents). Reading + replicating selected "
        "experiments.\n\n## Learnings\n\n- Memory-as-action vs context-stuffing trade-offs.\n",
    )
    store.write_file(
        "projects/code-llm-doc.md",
        {
            "project_id": "code-llm-doc",
            "cwd": "",
            "status": "active",
            "tags": ["writing", "docs"],
            "capabilities": [],
            "last_summarized_session": "2026-04-12",
        },
        "# Code-LLM Doc\n\n## Description\n\nWriting an internal doc on "
        "code-LLM evaluation methodology for the team.\n\n## Learnings\n\n- "
        "HumanEval saturation; need harder, runtime-grounded benchmarks.\n",
    )
    store.write_manifest(
        "projects",
        "# Projects Manifest\n\n"
        "- **cli-agent.md**       | active | CLI agent built from scratch in "
        "Python | cwd:/Users/bytedance/Projects/CLI-agent | "
        "tags: python, agents\n"
        "- **memact-research.md** | active | MemAct paper deep-dive — "
        "currently reading this paper, replicating experiments | "
        "tags: research, papers\n"
        "- **code-llm-doc.md**    | active | Internal doc on code-LLM "
        "evaluation methodology | tags: writing, docs\n",
    )

    # context/current.md (no manifest by spec)
    store.write_file(
        "context/current.md",
        {},
        "# Current week (2026-04-26 → 2026-05-02)\n\n"
        "- Shipping assistant memory system Phase 1.\n"
        "- Mom 2 weeks post-surgery, calling Sunday.\n"
        "- Sam visiting Singapore next month — need to plan dinners.\n",
    )

    # log/
    store.write_file(
        "log/2026-04/2026-04-15.md",
        {"date": "2026-04-15"},
        "# 2026-04-15\n\nCalled mom — surgery went well. Started MemAct deep-dive.\n",
    )
    store.write_file(
        "log/2026-03/2026-03-20.md",
        {"date": "2026-03-20"},
        "# 2026-03-20\n\nFlew to Tokyo with Alex for spring break. "
        "Hit Shibuya, day-tripped to Kamakura. Discussed possible Kyoto trip in fall.\n",
    )
    store.write_manifest(
        "log",
        "# Log Manifest\n\n"
        "## 2026-04 (current month)\n"
        "- Mom's surgery + recovery, weekly calls\n"
        "- Started MemAct paper deep-dive\n"
        "- Began assistant memory system Phase 1\n\n"
        "## 2026-03\n"
        "- Trip to Tokyo with Alex for spring break (visited Shibuya, Kamakura)\n"
        "- Jamie's breakup; started monthly check-ins\n"
        "- Began code-llm-doc draft\n",
    )

    return store


# ---------------------------------------------------------------------------
# Smart mock — parses prompt sections and returns plausible JSON
# ---------------------------------------------------------------------------


_PEOPLE_NAMES = ("alex", "mom", "jamie", "sam")
_PREF_KEYWORDS: dict[str, tuple[str, ...]] = {
    "preferences/coffee.md": ("coffee", "咖啡", "espresso", "v60", "beans"),
    "preferences/food.md": (
        "food", "餐厅", "餐", "restaurant", "cuisine", "eat", "dinner", "vegetarian",
        "sichuan", "spicy",
    ),
    "preferences/gifts.md": ("gift", "礼物", "present", "birthday gift"),
    "preferences/reading.md": ("read", "reading", "book", "书", "paper essays"),
    "preferences/travel.md": ("travel", "trip", "hotel", "旅行", "packing"),
}
_LOG_KEYWORDS = (
    "上个月", "last month", "去年", "last year", "去了哪", "去过", "history",
    "之前", "prior month", "previous month",
)
_PROJECT_KEYWORDS = (
    "项目", "project", "deep-dive", "论文", "paper", "正在做", "working on",
    "最近在做", "currently",
)


_SECTION_ANCHORS = (
    "# Recent turns",
    "# Index (_index.md)",
    "# Manifests",
    "# User query",
)


def _extract_section(prompt: str, header: str) -> str:
    """Slice between a known top-level section header and the next known one."""
    start = prompt.find(header + "\n")
    if start < 0:
        return ""
    body_start = start + len(header) + 1
    # Find the nearest next anchor
    end = len(prompt)
    for anchor in _SECTION_ANCHORS:
        if anchor == header:
            continue
        idx = prompt.find("\n" + anchor + "\n", body_start)
        if idx >= 0 and idx < end:
            end = idx
    return prompt[body_start:end].strip()


def _extract_query(prompt: str) -> str:
    return _extract_section(prompt, "# User query")


def _extract_recent(prompt: str) -> str:
    return _extract_section(prompt, "# Recent turns")


def _extract_manifests(prompt: str) -> str:
    return _extract_section(prompt, "# Manifests")


def _smart_stage1(query: str, recent: str) -> dict:
    """Decide scopes for a query by keyword matching."""
    q = (query + "\n" + recent).lower()
    scopes: list[str] = []

    if any(name in q for name in _PEOPLE_NAMES) or "kyoto" in q or "怎么样" in q:
        scopes.append("people")

    if any(
        kw in q
        for kws in _PREF_KEYWORDS.values()
        for kw in kws
    ):
        scopes.append("preferences")

    if any(kw in q for kw in _PROJECT_KEYWORDS):
        scopes.append("projects")

    if any(kw in q for kw in _LOG_KEYWORDS):
        scopes.append("log")

    # de-dup, preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    if not deduped:
        deduped = ["identity"]

    return {
        "scopes": deduped,
        "reasoning": f"keyword-match scopes={deduped} for query={query!r}",
    }


def _smart_stage2(query: str, recent: str, manifests: str) -> dict:
    """Pick files from manifests by keyword + manifest-line hooks."""
    q = (query + "\n" + recent).lower()
    files: list[str] = []
    why: list[str] = []

    # Walk each manifest line. Keep lines whose filename or hook text matches.
    for line in manifests.splitlines():
        m = re.search(r"\*\*([^*]+\.md)\*\*", line)
        if not m:
            continue
        fname = m.group(1)
        line_l = line.lower()

        # 1. People: name appears in query
        for name in _PEOPLE_NAMES:
            if fname == f"{name}.md" and name in q:
                rel = f"people/{name}.md"
                if rel not in files:
                    files.append(rel)
                    why.append(f"{name} mentioned")

        # 2. Kyoto / travel hook in alex line
        if fname == "alex.md" and "kyoto" in q and "kyoto" in line_l:
            rel = "people/alex.md"
            if rel not in files:
                files.append(rel)
                why.append("alex line has Kyoto hook")

        # 3. Preferences: topic keywords
        for rel, kws in _PREF_KEYWORDS.items():
            if rel.endswith(fname) and any(kw in q for kw in kws):
                if rel not in files:
                    files.append(rel)
                    why.append(f"pref hook {fname}")

        # 4. Projects: paper / deep-dive / current project
        if fname.endswith(".md") and "/projects/" not in manifests.lower() is False:
            pass  # placeholder; real logic below

    # Project selection — look at projects/_manifest.md content if present.
    if "Projects Manifest" in manifests or "projects/" in manifests.lower():
        # paper / deep-dive → memact-research
        if any(kw in q for kw in ("论文", "paper", "deep-dive", "deep dive")):
            rel = "projects/memact-research.md"
            if rel not in files and "memact-research.md" in manifests:
                files.append(rel)
                why.append("paper/deep-dive → memact-research")
        if any(kw in q for kw in ("最近在做", "项目", "正在做", "working on", "current project")):
            # pick top 1-2 active projects from manifest
            for line in manifests.splitlines():
                m = re.search(r"\*\*([^*]+\.md)\*\*\s*\|\s*active", line)
                if m:
                    rel = f"projects/{m.group(1)}"
                    if rel not in files:
                        files.append(rel)
                        why.append(f"active project {m.group(1)}")
                if len([f for f in files if f.startswith("projects/")]) >= 2:
                    break

    # Log scope: last-month / last-year heuristic — pick whatever 2026-03 file appears
    if "log" in manifests.lower() or "Log Manifest" in manifests:
        if any(kw in q for kw in ("上个月", "last month", "去了哪", "去过", "previous month")):
            # We don't have file names in the log manifest (monthly summaries),
            # but Stage 3 will load the scope. Return an empty list for log
            # is acceptable here — but we try to be helpful by including a
            # known prior-month file if visible.
            why.append("log query (prior month); no file-level hooks in manifest")

    # Cap 5
    return {
        "files": files[:5],
        "reasoning": "; ".join(why) if why else "no hooks matched",
    }


def _make_smart_client() -> MagicMock:
    """A MagicMock client whose chat.completions.create dispatches by prompt content."""
    client = MagicMock()

    def _create(model: str, messages: list, temperature: float = 0.0, **kwargs):
        prompt = messages[0]["content"]
        query = _extract_query(prompt)
        recent = _extract_recent(prompt)

        if "SCOPE SELECTOR" in prompt:
            payload = _smart_stage1(query, recent)
        elif "FILE SELECTOR" in prompt:
            manifests = _extract_manifests(prompt)
            payload = _smart_stage2(query, recent, manifests)
        else:
            # Curator or other — return empty/no-op JSON.
            payload = {"writes": [], "manifest_updates": []}

        msg = MagicMock()
        msg.content = json.dumps(payload)
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    client.chat.completions.create.side_effect = _create
    return client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        backend="deepseek",
        api_key="test-key",
        base_url="https://example.invalid",
        model_flash="deepseek-v4-flash",
        model_pro="deepseek-v4-pro",
        model="legacy",
        gpt_endpoint="",
        gpt_api_version="",
        max_tokens=4096,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_store(tmp_path: Path) -> AssistantMemoryStore:
    return _seed_memory(tmp_path)


@pytest.fixture
def pipeline(seeded_store: AssistantMemoryStore) -> RetrievalPipeline:
    client = _make_smart_client()
    with patch(
        "agent.assistant_memory.retrieval.create_client", return_value=client
    ):
        return RetrievalPipeline(seeded_store, _settings())


# ---------------------------------------------------------------------------
# Validation queries
# ---------------------------------------------------------------------------


# (id, query, expected_scopes_subset, expected_files_subset_or_scope_only)
# expected_files_subset uses None to mean "any file from this scope is enough"
QUERIES: list[tuple[int, str, set[str], set[str], str | None]] = [
    (1, "Alex 生日什么时候？", {"people"}, {"people/alex.md"}, None),
    (2, "下次见 mom 该带什么礼物？", {"people", "preferences"},
     {"people/mom.md", "preferences/gifts.md"}, None),
    (3, "我最近在做什么项目？", {"projects"}, set(), "projects"),
    (4, "我喜欢喝什么咖啡？", {"preferences"}, {"preferences/coffee.md"}, None),
    (5, "上个月我去了哪？", {"log"}, set(), "log"),
    (6, "Jamie 最近怎么样？", {"people"}, {"people/jamie.md"}, None),
    (7, "我应该给 Sam 推荐什么餐厅？", {"people", "preferences"},
     {"people/sam.md", "preferences/food.md"}, None),
    (8, "我去年这时候在做什么？", {"log"}, set(), "log"),
    (9, "我想去 Kyoto 是和谁说的？", {"people"}, {"people/alex.md"}, None),
    (10, "我现在正在 deep-dive 哪篇论文？", {"projects"},
     {"projects/memact-research.md"}, None),
]


def _run_query(
    pipeline: RetrievalPipeline, query: str
) -> tuple[list[str], list[str]]:
    stage1 = pipeline.select_scopes(query, [])
    files = pipeline.select_files(query, [], stage1.scopes)
    return stage1.scopes, files


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qid,query,exp_scopes,exp_files,scope_only",
    QUERIES,
    ids=[f"q{q[0]}" for q in QUERIES],
)
def test_retrieval_correctness_per_query(
    pipeline: RetrievalPipeline,
    qid: int,
    query: str,
    exp_scopes: set[str],
    exp_files: set[str],
    scope_only: str | None,
) -> None:
    scopes, files = _run_query(pipeline, query)
    scope_set = set(scopes)
    file_set = set(files)

    assert exp_scopes.issubset(scope_set), (
        f"q{qid} {query!r}: expected scopes {exp_scopes} not all in {scope_set}"
    )

    if scope_only is not None:
        # Scope-only target; no specific file required, but if files were
        # selected they must be coherent (at minimum, scope present). The
        # assertion above already covers that.
        return

    assert exp_files.issubset(file_set), (
        f"q{qid} {query!r}: expected files {exp_files} not all in {file_set}"
    )


def test_retrieval_aggregate_score(pipeline: RetrievalPipeline) -> None:
    """At least 8/10 of the spec validation queries must pass."""
    passed = 0
    failures: list[str] = []
    for qid, query, exp_scopes, exp_files, scope_only in QUERIES:
        scopes, files = _run_query(pipeline, query)
        scope_set = set(scopes)
        file_set = set(files)

        ok = exp_scopes.issubset(scope_set)
        if scope_only is None:
            ok = ok and exp_files.issubset(file_set)

        if ok:
            passed += 1
        else:
            failures.append(
                f"q{qid} {query!r}: scopes={scopes} files={files} "
                f"want_scopes={exp_scopes} want_files={exp_files}"
            )

    assert passed >= 8, (
        f"Only {passed}/10 queries passed; failures:\n  "
        + "\n  ".join(failures)
    )


def test_immutable_core_always_in_system_prompt(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    client = _make_smart_client()
    with patch(
        "agent.assistant_memory.retrieval.create_client", return_value=client
    ), patch(
        "agent.assistant_memory.curator.create_client", return_value=client
    ):
        manager = AssistantMemoryManager(str(tmp_path), _settings())
        prompt = manager.on_startup()

    assert "Be genuinely helpful" in prompt
    assert "Private things stay private" in prompt


def test_current_context_always_included(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    client = _make_smart_client()
    with patch(
        "agent.assistant_memory.retrieval.create_client", return_value=client
    ), patch(
        "agent.assistant_memory.curator.create_client", return_value=client
    ):
        manager = AssistantMemoryManager(str(tmp_path), _settings())
        prompt = manager.on_startup()

    assert "Shipping assistant memory system Phase 1" in prompt
    assert "Sam visiting Singapore next month" in prompt

"""Prompt templates for the assistant memory pipeline.

All prompts use {var} placeholders for str.format substitution. Outputs are
JSON-only where applicable; downstream parsers must reject anything else.
"""

from __future__ import annotations


STAGE1_SCOPE_PROMPT = """You are the SCOPE SELECTOR for a personal-assistant memory system.

Your job: given the user's query, recent conversation, and the top-level memory index,
decide which memory scopes are likely to contain relevant information.

Available scopes (from the index):
- identity/      — who the user is + agent's own soul
- people/        — people in the user's life
- preferences/   — user's tastes and habits
- projects/      — active and past projects
- log/           — event history (monthly summaries available)

Note: `context/current.md` is always loaded automatically. Do NOT include it.

# Recent turns
{recent_turns}

# Index (_index.md)
{index_md}

# User query
{user_query}

Respond with JSON only, no commentary, no markdown fences:
{{"scopes": ["people", "preferences"], "reasoning": "<one sentence>"}}

Be aggressive about exclusion. Prefer 1-3 scopes. Empty list is allowed if nothing fits.
"""


STAGE2_FILE_PROMPT = """You are the FILE SELECTOR for a personal-assistant memory system.

Given the user's query, recent turns, and the manifests of the scopes already chosen,
pick at most 5 specific files whose contents are likely needed to answer.

# Recent turns
{recent_turns}

# Manifests
{manifests}

# User query
{user_query}

Respond with JSON only, no commentary, no markdown fences:
{{"files": ["people/alex.md", "preferences/food.md"], "reasoning": "<one sentence>"}}

Cap: 5 files total. Be aggressive about exclusion — every extra file costs context.
"""


MAIN_RESPONSE_PROMPT = """# User
{user_summary}

# Current context (context/current.md)
{current_context}

# Retrieved memories
{memories}

# Recent turns
{recent_turns}

# User query
{user_query}

Answer the user directly and naturally.

Honesty about gaps: if the retrieved memories don't actually contain a fact the user is
asking about (e.g. someone's birthday, a preference, a past event), say so plainly and
ask the user for it. Do NOT guess, do NOT paper over the gap with vague language, and
do NOT pretend to remember. Acknowledging "I don't have that yet — want to tell me?"
is always better than fabricating.

If the user then provides the answer, treat it as a confirmed fact worth saving
(the curator will pick it up).

If you notice something that should update memory, mention it briefly at the end as:
`[memory note: ...]`
"""


CURATOR_PROMPT = """You are the CURATOR for a personal-assistant memory system.

You receive the last user message and the last assistant message (which may contain
`[memory note: ...]` markers). Your job is to decide what, if anything, should be written
to long-term memory, and to propose minimal incremental manifest line updates.

Layers:
- Layer 1 (silent write): trivial, unambiguous extraction. Example: user says
  "I'm allergic to peanuts" -> append to preferences/food.md.
- Layer 2 (confirm write): ambiguous, contradicting, or sensitive. Surface to user
  before writing.

If unsure between layer 1 and layer 2, choose 2.

Special rule — agent identity edits: any write to `identity/agent.md` (the agent's own
soul / personality) is ALWAYS Layer 2. Never silent-write the agent's personality.
The `immutable_core` frontmatter field MUST NOT be modified — refuse such writes.
Soul body edits should be conservative: prefer small additive nudges over rewrites.

Operations:
- "append"        — add content to end of file body
- "update_field"  — set a frontmatter field
- "create"        — new file (provide full frontmatter + body in `content`)

Manifest updates: one entry per affected manifest line. `line_key` identifies the line
(typically the filename). `new_line` is the full replacement line text. Omit if no
manifest-relevant attribute changed.

Respond with JSON only, no commentary, no markdown fences:
{{
  "writes": [
    {{
      "file": "people/alex.md",
      "operation": "append",
      "content": "...",
      "layer": 1,
      "reason": "<one sentence>"
    }}
  ],
  "manifest_updates": [
    {{"scope": "people", "line_key": "alex.md", "new_line": "- **alex.md** | ..."}}
  ]
}}

Empty arrays are fine if nothing should change.
"""


CONSOLIDATION_PROMPT = """You are the CONSOLIDATION pass at the end of an assistant session.

Unlike the per-turn curator (which sees only 1-2 messages), you see the FULL transcript
and the current memory manifests. Your job: extract durable facts that were repeated,
strengthened, or newly established across multiple turns — facts the per-turn curator
may have missed because they only became clear in aggregate.

Examples of what to consolidate:
- A goal or interest mentioned 2+ times → add to identity/me.md or relevant project.
- A person mentioned 2+ times by name with attributes → create or update people/<name>.md.
- A preference reinforced or corrected across the session → update preferences/<topic>.md.
- A new project the user is working on → create projects/<id>.md.

Forbidden writes (never propose):
- `identity/agent.md` — the agent's soul. Soul evolution is out of scope here.
- `identity/me.md` immutable fields (email, birthday, school) unless user explicitly stated
  a change this session. Adding new sub-bullets to existing sections is fine.
- `context/current.md` — user-maintained, never auto-edit.
- Anything contradicting an existing immutable_core or frontmatter `immutable: true` field.

Conservative rule: if a "fact" only came up ONCE and wasn't directly stated as durable,
SKIP IT. Single-mention noise is the per-turn curator's job, not yours. You synthesize.

Output JSON only, same shape as the per-turn curator. All writes are applied silently
(no confirm gate), so quality > quantity. Empty arrays are the right answer for short
or low-signal sessions.

# Current manifests
{manifests}

# Full transcript
{transcript}

JSON:
"""


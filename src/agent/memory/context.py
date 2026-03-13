"""Assemble memory context for injection into the system prompt."""

from agent.memory.config import MemoryConfig
from agent.memory.models import Personality, Project, SessionDigest
from agent.memory.tokens import count_tokens, truncate_to_tokens


def assemble_context(
    personality: Personality | None,
    project: Project | None,
    last_digest: SessionDigest | None,
    config: MemoryConfig,
) -> str:
    """Build system prompt preamble from personality, project, and digest within token budget."""
    if personality is None and project is None and last_digest is None:
        return ""

    sections: list[str] = []
    tokens_used = 0

    # 3. Personality section (always included in full, even if over budget)
    if personality is not None:
        person_section = f"""## Core Identity
{personality.immutable_core}

## Soul
{personality.soul}"""
        sections.append(person_section)
        tokens_used += count_tokens(person_section)

    # 4. Budget remaining
    remaining = config.context_token_budget - tokens_used

    # 5. Last digest section (include whole or skip entirely)
    if remaining > 0 and last_digest is not None:
        digest_section = f"""## Previous Session
{last_digest.summary}
Capabilities: {", ".join(last_digest.capabilities)}
Learnings: {last_digest.learnings}"""
        digest_tokens = count_tokens(digest_section)
        if digest_tokens <= remaining:
            sections.append(digest_section)
            remaining -= digest_tokens

    # 6. Project learnings section (truncate to fit remaining)
    if project is not None and project.learnings != "":
        cap = min(remaining, config.learnings_max_tokens)
        if cap > 0:
            truncated = truncate_to_tokens(project.learnings, cap)
            learnings_section = f"""## Project Context
{truncated}"""
            sections.append(learnings_section)

    return "\n\n".join(sections)

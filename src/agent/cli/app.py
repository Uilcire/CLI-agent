"""REPL entry point: run the agent in an interactive loop."""

import os
import sys
from pathlib import Path

from agent.logger import get_logger
from agent.config.settings import load_settings
from agent.cli.display import print_banner, prompt_user, stream_assistant
from agent.core.loop import run_streaming
from agent.core.state import ConversationState
from agent.memory.manager import MemoryManager
from agent.skills.discovery import discover_skills
from agent.skills.manager import SkillManager
from agent.tools import registry as tool_registry
from agent.tools.read_skill import read_skill as _read_skill

log = get_logger(__name__)


def _resolve_project(memory: MemoryManager, cwd: str) -> str | None:
    """
    Determine project_id for this session via user interaction.
    Three outcomes: resume existing, onboard new, link to existing, or skip.
    Returns project_id string or None.
    """
    existing = memory.find_project_for_cwd(cwd)

    if existing is not None:
        print(f"Resuming project: {existing.description} [{', '.join(existing.tags)}]")
        from agent.memory.onboarding import cwd_project_id
        return cwd_project_id(cwd)

    print("No project found for this directory.")
    try:
        choice = input("Start a new project, or link to an existing one? [new/existing/skip]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nSkipping project setup.")
        return None

    if choice == "new":
        project = memory.onboard_for_cwd(cwd, print_fn=print)
        return project.project_id if project else None

    if choice == "existing":
        projects = memory._store.list_projects()
        if not projects:
            print("No existing projects found. Starting without project context.")
            return None
        print("\nExisting projects:")
        for i, p in enumerate(projects, 1):
            tags = ", ".join(p.tags) or "no tags"
            print(f"  [{i}] {p.description} — {tags} | {len(p.sessions)} sessions")
        try:
            raw = input("\nEnter number (or 0 to skip): ").strip()
            idx = int(raw)
            if 1 <= idx <= len(projects):
                chosen = projects[idx - 1]
                print(f"Linked to: {chosen.description}")
                return chosen.project_id
        except (ValueError, EOFError):
            pass
        print("Starting without project context.")
        return None

    print("Starting without project context.")
    return None


def main() -> None:
    """Run the CLI agent REPL."""
    try:
        settings = load_settings()
        log.info("Settings loaded: model=%s, max_tokens=%s", settings.model, settings.max_tokens)
    except ValueError as e:
        log.error("Settings error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print_banner()
    print("Type a message or 'quit' to exit.")
    log.info("Agent started, waiting for user input")

    memory_dir_raw = os.environ.get("MEMORY_DIR", "./agent-memory")
    memory_dir = os.path.abspath(os.path.expanduser(memory_dir_raw))
    os.makedirs(memory_dir, exist_ok=True)
    log.info("Memory directory: %s", memory_dir)
    memory = MemoryManager(data_dir=memory_dir, settings=settings)
    cwd = os.getcwd()
    project_id = _resolve_project(memory, cwd)
    memory_context = memory.on_startup(project_id=project_id)

    # Discover skills and build catalog section for the system prompt.
    skill_manager = SkillManager(discover_skills(Path(cwd)))
    log.info("Skills loaded: %d", len(skill_manager.names()))

    base_prompt = (
        "You are a helpful cli code assistant.\n\n"
        "Problem-solving: Always try your best to find a way to solve problems asked by users. "
        "Do not simply say \"it's not in my capability\". If the current tools or skills do not allow you to accomplish the task, "
        "write new tools and skills to achieve it. If you don't have enough information to do something, always use the web_search tool.\n\n"
        "Action first: For simple questions (e.g. 'what are today's headlines?'), do not ask for permission or clarification—assume from the user's perspective and take action (e.g. use web_search). When you do so, briefly explain your rationale so the user knows what decisions or assumptions you made and why.\n\n"
        "Facts: Always use web_search to gather and verify information before answering. Do not rely on prior knowledge alone—always search and verify.\n\n"
        "For deletions: When the user confirms they want to delete (e.g. 'yes', 'delete it', 'go ahead'), "
        "call delete_file or delete_dir directly. Do not ask for explicit text formats like 'DELETE ./path'. "
        "A confirmation dialog will automatically pop up when permission has not been granted this session.\n\n"
        "Output formatting: Only call the beautify tool when your response text would be hard for humans to read "
        "(e.g. dense blocks, poor structure, unclear formatting). If it's already clear, present it as-is."
    )

    parts = []
    if memory_context:
        parts.append(memory_context)
    if not skill_manager.is_empty():
        parts.append(skill_manager.catalog_xml())
        parts.append(
            "When a task matches a skill's description, call the `read_skill` tool "
            "with the skill's name to load its full instructions before proceeding. "
            "Skills tell you which shell commands to run; use the `bash` tool to "
            "execute them. When a skill references relative paths, resolve them "
            "against the skill directory shown in the skill content."
        )
    parts.append(base_prompt)
    system_prompt = "\n\n".join(parts)

    state = ConversationState(system_prompt=system_prompt)

    # Wire the skill manager and state into the tool registry.
    tool_registry.init(skill_manager, state)

    try:
        while True:
            try:
                user_input = prompt_user()
            except KeyboardInterrupt:
                log.info("Agent stopped by user (Ctrl+C)")
                print("\nBye.")
                break
            if not user_input or user_input.lower() in ("quit", "exit"):
                log.info("Agent stopped by user (quit/exit)")
                print("Bye.")
                break
            cmd_result = memory.handle_command(user_input)
            if cmd_result is not None:
                print(cmd_result)
                continue

            # /skills — list available skills
            if user_input.strip() == "/skills":
                if skill_manager.is_empty():
                    print("No skills installed.")
                else:
                    for r in skill_manager.skills.values():
                        print(f"  [{r.scope}] {r.name} — {r.description}")
                continue

            # /skill-name — explicit skill activation
            if user_input.startswith("/") and not user_input.startswith("/memory"):
                skill_name = user_input[1:].strip().lower()
                if skill_manager.get(skill_name):
                    content = _read_skill(skill_name, skill_manager, state)
                    state.add_user_message(f"Please load the '{skill_name}' skill.")
                    state.add_assistant_message(content)
                    print(f"Skill '{skill_name}' loaded into context.")
                    continue
                # Unknown slash command — fall through to the agent loop
            log.info("User message received: %s", user_input[:100] + ("..." if len(user_input) > 100 else ""))
            events = run_streaming(user_input, settings, state=state)
            final_text = stream_assistant(events)
            log.info("Turn complete, assistant reply length=%d chars", len(final_text) if final_text else 0)
            memory.on_user_turn(user_input)
            memory.on_assistant_turn(final_text or "")
    finally:
        status = memory.on_exit()
        if status:
            print(status)

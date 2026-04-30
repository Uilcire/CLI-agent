"""REPL entry point: run the agent in an interactive loop."""

import os
import signal
import sys
from pathlib import Path

from agent.logger import get_logger
from agent.config.settings import load_settings
from agent.cli.display import print_banner, prompt_user, stream_assistant
from agent.core.loop import run_streaming
from agent.core.state import ConversationState
from agent.assistant_memory.manager import AssistantMemoryManager
from agent.skills.discovery import discover_skills
from agent.skills.manager import SkillManager
from agent.tools import registry as tool_registry
from agent.tools.read_skill import read_skill as _read_skill

log = get_logger(__name__)


def _resolve_project(memory: AssistantMemoryManager, cwd: str) -> str | None:
    """
    Determine project_id for this session via user interaction.
    Three outcomes: resume existing, onboard new, link to existing, or skip.
    Returns project_id string or None.
    """
    existing = memory.find_project_for_cwd(cwd)

    if existing is not None:
        print(f"Resuming project: {existing.description} [{', '.join(existing.tags)}]")
        return existing.project_id

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
        # Listing existing projects from the new markdown layout is best-effort.
        files = memory.store.list_files("projects")
        if not files:
            print("No existing projects found. Starting without project context.")
            return None
        print("\nExisting projects:")
        for i, rel in enumerate(files, 1):
            meta, _ = memory.store.read_file(rel)
            desc = meta.get("project_id") or rel
            tags = ", ".join(meta.get("tags") or []) or "no tags"
            print(f"  [{i}] {desc} — {tags}")
        try:
            raw = input("\nEnter number (or 0 to skip): ").strip()
            idx = int(raw)
            if 1 <= idx <= len(files):
                chosen_rel = files[idx - 1]
                meta, _ = memory.store.read_file(chosen_rel)
                chosen_id = str(meta.get("project_id") or chosen_rel)
                print(f"Linked to: {chosen_id}")
                return chosen_id
        except (ValueError, EOFError):
            pass
        print("Starting without project context.")
        return None

    print("Starting without project context.")
    return None


def _enable_memlog() -> None:
    """Render agent.assistant_memory log records as orange MEMORY panels (mirror of TOOL CALL)."""
    import logging
    from agent.cli.display import print_mem_event, set_memlog_enabled

    set_memlog_enabled(True)

    class _MemPanelHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                print_mem_event(record.getMessage())
            except Exception:  # pragma: no cover
                pass

    handler = _MemPanelHandler(level=logging.INFO)
    mem_logger = logging.getLogger("agent.assistant_memory")
    mem_logger.setLevel(logging.INFO)
    mem_logger.addHandler(handler)
    mem_logger.propagate = False


def main() -> None:
    """Run the CLI agent REPL."""
    argv = sys.argv[1:]
    memlog = any(a in ("-memlog", "--memlog") for a in argv)
    if memlog:
        _enable_memlog()

    try:
        settings = load_settings()
        log.info("Settings loaded: model=%s, max_tokens=%s", settings.model, settings.max_tokens)
    except ValueError as e:
        log.error("Settings error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print_banner()
    if memlog:
        print("Memory log mode ON — retrieval/curator/consolidation events shown as orange MEMORY panels.")
    print("Type a message or 'quit' to exit.")
    log.info("Agent started, waiting for user input")

    # Prefer the centralized helper if Wave A has wired it up; fall back to
    # the existing precedence (ASSISTANT_MEMORY_DIR > MEMORY_DIR > default).
    try:
        from agent.assistant_memory.schema import get_memory_dir as _get_memory_dir
    except ImportError:
        _get_memory_dir = None  # type: ignore[assignment]

    if _get_memory_dir is not None and os.environ.get("ASSISTANT_MEMORY_DIR"):
        memory_dir = str(_get_memory_dir())
    else:
        memory_dir_raw = (
            os.environ.get("ASSISTANT_MEMORY_DIR")
            or os.environ.get("MEMORY_DIR")
            or "~/assistant-memory"
        )
        memory_dir = os.path.expanduser(memory_dir_raw)
    memory_dir = os.path.abspath(memory_dir)
    os.makedirs(memory_dir, exist_ok=True)
    log.info("Memory directory: %s", memory_dir)
    memory = AssistantMemoryManager(data_dir=memory_dir, settings=settings)
    cwd = os.getcwd()
    project_id = _resolve_project(memory, cwd)
    memory_context = memory.on_startup(project_id=project_id)

    # Discover skills and build catalog section for the system prompt.
    skill_manager = SkillManager(discover_skills(Path(cwd)))
    log.info("Skills loaded: %d", len(skill_manager.names()))

    # Load AGENT.md identity/operating-context file (project takes priority over user).
    agent_md = ""
    for p in (Path(cwd) / ".agents" / "AGENT.md", Path.home() / ".agents" / "AGENT.md"):
        if p.is_file():
            try:
                agent_md = p.read_text(encoding="utf-8").strip()
                log.info("Loaded AGENT.md from %s (%d chars)", p, len(agent_md))
            except OSError as e:
                log.warning("Cannot read AGENT.md at %s: %s", p, e)
            break

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
        "Output formatting: Your output is rendered through Rich Markdown in the terminal. "
        "Use markdown freely for readability: **bold**, `code`, ```code blocks```, ### headers, "
        "- lists, 1. numbered lists. It will look clean and formatted. "
        "For dense or poorly structured output, call the beautify tool."
    )

    parts = []
    if memory_context:
        parts.append(memory_context)
    if agent_md:
        parts.append(agent_md)
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

    turn_count = 0

    # Two-press Ctrl+C: first press = clean break out of REPL via KeyboardInterrupt,
    # second press = hard exit (skips finally, kills daemon threads). Useful when an
    # LLM network call is mid-flight and the join timeout feels like a hang.
    _sigint_count = {"n": 0}

    def _sigint_handler(signum, frame):
        _sigint_count["n"] += 1
        if _sigint_count["n"] >= 2:
            os._exit(130)
        # First press: let default KeyboardInterrupt fire by re-raising
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        while True:
            try:
                user_input = prompt_user()
            except (KeyboardInterrupt, EOFError):
                log.info("Agent stopped by user (Ctrl+C / EOF)")
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

            turn_count += 1
            _sigint_count["n"] = 0  # reset two-press counter for the new turn

            try:
                log.info("User message received: %s", user_input[:100] + ("..." if len(user_input) > 100 else ""))

                # Two-stage retrieval, injected as a transient system suffix
                # for this turn only. Empty string = no injection.
                mem_block = memory.retrieve_for_query(user_input)
                if mem_block:
                    state.set_transient_system_suffix(mem_block)
                    log.info("Memory injected: %d chars", len(mem_block))

                events = run_streaming(user_input, settings, state=state)
                final_text = stream_assistant(events)
                log.info("Turn complete, assistant reply length=%d chars", len(final_text) if final_text else 0)
                memory.on_user_turn(user_input)
                # final_text retains [memory note: ...] for the curator to parse;
                # display layer is responsible for hiding it from the user.
                memory.on_assistant_turn(final_text or "")
            except KeyboardInterrupt:
                # User hit ^C mid-turn — abort cleanly, drop back to prompt.
                # Hitting ^C again at the prompt will exit the REPL.
                log.info("Turn interrupted by user (Ctrl+C)")
                print("\n[interrupted]")
    finally:
        status = memory.on_exit()
        if status:
            print(status)

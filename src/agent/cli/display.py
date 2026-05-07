"""Display layer: pretty-print assistant output using Rich."""

import queue
import re
import threading
from typing import Literal

from rich.console import Console, Group
from rich.panel import Panel
from rich.box import ROUNDED, HEAVY
from rich.markup import escape
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.live import Live
from rich.text import Text

# Neon blue hex
NEON_BLUE = "#00d4ff"
DeleteChoice = Literal["delete_grant", "delete_no_grant", "cancel"]
# Prompt: "You:" in bold green
PROMPT_STYLE = "bold light_green"

# Tool call / result box styles
TOOL_CALL_BORDER = "#8B5CF6"  # purple-violet
TOOL_RESULT_BORDER = "#6B7280"  # dim gray
MEM_BORDER = "#FB923C"  # orange — memory events

# Cat ASCII art and bubble tail — assistant speaks from diagonally above the cat
_CAT_ART = " /\\_/\\\n( o.o )\n > ^ < "
_BUBBLE_TAIL = "  ╰──╮"
_CAT_INDENT = "      "


def _cat_bubble(content) -> Group:
    """Wrap *content* in a speech bubble with the cat below-right."""
    bubble = Panel(
        content,
        title=f"[bold {NEON_BLUE}]🐱[/bold {NEON_BLUE}]",
        border_style=NEON_BLUE,
        box=ROUNDED,
        padding=(0, 1),
    )
    tail = Text(_BUBBLE_TAIL, style="dim")
    cat = Text("\n".join(_CAT_INDENT + line for line in _CAT_ART.splitlines()),
               style="bright_white")
    return Group(bubble, tail, cat)


def _has_markdown(text: str) -> bool:
    """Quick check if text contains markdown formatting characters."""
    import re
    pattern = (
        r'(\*\*|__|`|~~|'              # bold / code / strikethrough
        r'(?<!\w)\*[^*\s][^*]*\*(?!\w)|'  # *italic*
        r'(?<!\w)_[^_\s][^_]*_(?!\w)|'    # _italic_
        r'^#{1,6}\s|'                    # headers
        r'^[-*+]\s|^\d+\.\s|^>|'         # lists / blockquote
        r'^\s*[-*_]{3,}\s*$|'            # hr
        r'\|.*\|.*\||'                   # table row
        r'\[[^\]]+\]\([^)]+\))'          # [text](url)
    )
    return bool(re.search(pattern, text, re.MULTILINE))


def _balance_fences(text: str) -> str:
    """If text has an odd number of ``` fences (mid-stream), append a closing
    fence so the in-progress Markdown render doesn't swallow trailing prose."""
    if text.count("```") % 2 == 1:
        return text + "\n```"
    return text


_MEMORY_NOTE_INLINE_RE = re.compile(r"\[memory note:[^\]]*\]", re.IGNORECASE | re.DOTALL)
# Lower-case, prefix is what we watch for while bytes drip in.
_MEMNOTE_PREFIX = "[memory note:"


class _MemNoteFilter:
    """Strip ``[memory note: ...]`` markers from a stream of deltas.

    State machine:
    - normal: emit chars; on encountering ``[``, hold it.
    - holding: accumulate chars; if accumulated string is no longer a prefix
      of ``[memory note:``, flush it. If we reach the full marker prefix,
      switch to swallowing until ``]``.
    - swallowing: drop chars until we see ``]``; then back to normal.
    """

    def __init__(self) -> None:
        self._held: str = ""
        self._swallowing: bool = False

    def feed(self, delta: str) -> str:
        out: list[str] = []
        for ch in delta:
            if self._swallowing:
                if ch == "]":
                    self._swallowing = False
                continue
            if self._held:
                self._held += ch
                lowered = self._held.lower()
                if lowered.startswith(_MEMNOTE_PREFIX):
                    # Found the full prefix; switch to swallow mode.
                    self._held = ""
                    self._swallowing = True
                    continue
                if not _MEMNOTE_PREFIX.startswith(lowered):
                    # No longer a possible prefix — flush, reset.
                    out.append(self._held)
                    self._held = ""
                continue
            if ch == "[":
                self._held = ch
                continue
            out.append(ch)
        return "".join(out)

    def flush(self) -> str:
        held, self._held = self._held, ""
        if self._swallowing:
            # Unterminated marker — drop it.
            self._swallowing = False
            return ""
        return held


# ---- Memory-event panel queueing (deferred while Rich Live is active) ------

_mem_event_queue: "queue.Queue[str]" = queue.Queue()
_live_active_lock = threading.Lock()
_live_active: bool = False
_memlog_enabled: bool = False


def set_memlog_enabled(enabled: bool) -> None:
    global _memlog_enabled
    _memlog_enabled = bool(enabled)


def mem_live_active(active: bool) -> None:
    """Toggle the Live-active flag from ``stream_assistant``."""
    global _live_active
    with _live_active_lock:
        _live_active = bool(active)


def drain_mem_events() -> None:
    """Render any deferred memory panels. Call from main thread after Live ends."""
    while True:
        try:
            msg = _mem_event_queue.get_nowait()
        except queue.Empty:
            return
        _render_mem_panel(msg)


def stream_assistant(events) -> str:
    """
    Consume streaming events, render content through Rich Markdown
    for readable terminal output. Switches to raw mode during/after
    tool calls since Markdown rendering can't overlay tool output cleanly.
    Returns the final assistant text.
    """
    console = Console()
    content_parts: list[str] = []
    final_text = ""
    tool_mode = False
    note_filter = _MemNoteFilter()

    # Live display for in-progress markdown rendering (inside cat bubble)
    live = Live(
        _cat_bubble(Markdown("", code_theme="monokai")),
        console=console,
        refresh_per_second=10,
        transient=False,
        vertical_overflow="visible",
    )

    try:
        for event_type, data in events:
            if event_type == "content_delta":
                if tool_mode:
                    # Resume markdown rendering for the new post-tool segment
                    tool_mode = False
                    content_parts = []
                visible = note_filter.feed(data["delta"])
                if not visible:
                    continue
                content_parts.append(visible)
                accum = "".join(content_parts)
                if not live.is_started:
                    live.start()
                    mem_live_active(True)
                live.update(_cat_bubble(Markdown(_balance_fences(accum), code_theme="monokai")))

            elif event_type == "tool_call":
                # Pause markdown rendering — tool output can't overlay a Live region
                if not tool_mode:
                    if live.is_started:
                        live.stop()
                        mem_live_active(False)
                        drain_mem_events()
                    tool_mode = True
                    if content_parts:
                        console.print()  # newline after rendered markdown
                name, args = data["name"], data["args"]
                args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
                tool_call_markup = (
                    f"[bold bright_white]⟳ {escape(str(name))}[/bold bright_white]\n"
                    f"[dim]{escape(args_str)}[/dim]"
                )
                console.print(
                    Panel(
                        tool_call_markup,
                        title="[bold]🔧 TOOL CALL[/bold]",
                        border_style=TOOL_CALL_BORDER,
                        box=HEAVY,
                        padding=(0, 1),
                    )
                )

            elif event_type == "tool_result":
                name, result = data["name"], data["result"]
                result_preview = result[:300] + ("..." if len(result) > 300 else "")
                tool_result_markup = (
                    f"[bold bright_white]{escape(str(name))}[/bold bright_white]\n"
                    f"[dim italic]{escape(result_preview)}[/dim italic]"
                )
                console.print(
                    Panel(
                        tool_result_markup,
                        title="[bold]📤 RESULT[/bold]",
                        border_style=TOOL_RESULT_BORDER,
                        box=ROUNDED,
                        padding=(0, 1),
                    )
                )

            elif event_type == "done":
                # final_text is the full turn text (used as return value).
                # Do NOT re-render it into the current Live region — that region
                # only owns the post-last-tool segment, and content_delta already
                # streamed it. Re-rendering full text would duplicate pre-tool prose.
                final_text = data.get("text", "")
                break
    finally:
        # Flush any remaining buffered char (e.g. dangling "[" not part of a marker).
        tail = note_filter.flush()
        if tail and live.is_started:
            content_parts.append(tail)
            live.update(_cat_bubble(Markdown(_balance_fences("".join(content_parts)), code_theme="monokai")))
        if live.is_started:
            live.stop()
        mem_live_active(False)
        if tool_mode:
            console.print()  # flush raw output
        drain_mem_events()

    return final_text


def print_banner() -> None:
    """Print the CLI agent banner on startup (neon blue, rounded border)."""
    console = Console()
    console.print(
        Panel(
            "[bold]" + "欢迎使用 Eric 的 CLI agent :D (版本0.1.0)" + "[/bold]",
            style=NEON_BLUE,
            box=ROUNDED,
        )
    )


def print_assistant(text: str) -> None:
    """Print assistant reply as a cat speech bubble."""
    console = Console()
    if not text or not text.strip():
        return
    content = Markdown(text, code_theme="monokai") if _has_markdown(text) else Text(text)
    console.print(_cat_bubble(content))


def prompt_user() -> str:
    """Show "You:" in bold green and return user input."""
    console = Console()
    w = console.width
    result = console.input(f"[{PROMPT_STYLE}]You:[/{PROMPT_STYLE}]\n").strip()
    return result


def confirm_delete(path: str) -> DeleteChoice:
    """
    Show a permission box for deleting a file or directory.
    Returns one of: "delete_grant", "delete_no_grant", "cancel".
    When stdin is not a TTY (e.g. piped input), defaults to cancel.
    """
    import sys
    if not sys.stdin.isatty():
        return "cancel"
    console = Console()
    options = (
        f"[dim]1.[/dim] Delete [cyan]{escape(path)}[/cyan] and grant permission to delete its contents in the future\n"
        f"[dim]2.[/dim] Delete [cyan]{escape(path)}[/cyan] and do not grant future permission\n"
        f"[dim]3.[/dim] Do not delete"
    )
    content = f"Permission to delete?\n\n{options}\n"
    console.print(
        Panel(
            content,
            title="[bold]Confirm Delete[/bold]",
            border_style="yellow",
            box=ROUNDED,
        )
    )
    choice = Prompt.ask(
        "Choose",
        choices=["1", "2", "3"],
        default="3",
    )
    return {"1": "delete_grant", "2": "delete_no_grant", "3": "cancel"}[choice]


_mem_console = Console()


def _render_mem_panel(message: str) -> None:
    _mem_console.print(
        Panel(
            f"[bold bright_white]🧠 {escape(message)}[/bold bright_white]",
            title="[bold]MEMORY[/bold]",
            border_style=MEM_BORDER,
            box=HEAVY,
            padding=(0, 1),
        )
    )


def print_mem_event(message: str) -> None:
    """Render a memory event as an orange-bordered panel.

    If a Rich ``Live`` region is currently active (assistant streaming), defer
    the panel to a queue and let ``stream_assistant`` drain it after Live ends.
    """
    if not _memlog_enabled:
        return
    with _live_active_lock:
        active = _live_active
    if active:
        _mem_event_queue.put(message)
        return
    _render_mem_panel(message)

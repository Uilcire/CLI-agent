"""ReAct agent loop: call model, execute tools, repeat until done."""

import json
from typing import Generator

from agent.config.settings import Settings
from agent.core.state import ConversationState
from agent.llm.client import create_client
from agent.logger import get_logger, is_log_debug
from agent.tools.registry import execute, get_tools

log = get_logger(__name__)

# Default system prompt used when no state is provided (loop fallback, run(), Feishu base).
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful cli code assistant.\n\n"
    "Problem-solving: Always try your best to find a way to solve problems asked by users. "
    "Do not simply say \"it's not in my capability\". If the current tools or skills do not allow you to accomplish the task, "
    "write new tools and skills to achieve it. If you don't have enough information to do something, always use the web_search tool.\n\n"
    "Action first: For simple questions (e.g. 'what are today's headlines?'), do not ask for permission or clarification—assume from the user's perspective and take action (e.g. use web_search). When you do so, briefly explain your rationale so the user knows what decisions or assumptions you made and why.\n\n"
    "Facts: Always use web_search to gather and verify information before answering. Do not rely on prior knowledge alone—always search and verify.\n\n"
    "The current project is your own source code—you are more than welcome to edit it, including this system prompt and the agent logic. "
    "Use read_file, search_replace, write, and other tools to modify the codebase as needed.\n\n"
    "For deletions: When the user confirms they want to delete (e.g. 'yes', 'delete it', 'go ahead'), "
    "call delete_file or delete_dir directly. Do not ask for explicit text formats like 'DELETE ./path'. "
    "A confirmation dialog will automatically pop up when permission has not been granted this session.\n\n"
    "Output formatting: Your output is rendered through Rich Markdown in the terminal. "
    "Use markdown freely for readability: **bold**, `code`, ```code blocks```, ### headers, "
    "- lists, 1. numbered lists. It will look clean and formatted. "
    "For dense or poorly structured output, call the beautify tool."
)

# Stream event types: (type, data)
# - ("content_delta", {"delta": str})
# - ("tool_call", {"name": str, "args": dict, "id": str})
# - ("tool_result", {"name": str, "result": str})
# - ("done", {"text": str})


def run_streaming(
    user_message: str,
    settings: Settings,
    state: ConversationState | None = None,
) -> Generator[tuple[str, dict], None, str]:
    """
    Run one user turn with streaming. Yields (event_type, data) tuples.

    Events: content_delta, tool_call, tool_result, done.

    If state is provided, appends the user message and continues the conversation.
    If state is None, creates a fresh conversation (single-turn).
    """
    if state is None:
        state = ConversationState(system_prompt=DEFAULT_SYSTEM_PROMPT)
    state.add_user_message(user_message)

    client = create_client(settings)
    tools = get_tools()
    log.debug("ReAct loop started, backend=%s, messages=%d", settings.backend, len(state.get_messages()))

    transient_suffix = state.consume_transient_system_suffix()

    def build_messages() -> list[dict]:
        msgs = []
        sys_parts: list[str] = []
        if state.system_prompt:
            sys_parts.append(state.system_prompt)
        if transient_suffix:
            sys_parts.append(transient_suffix)
        if sys_parts:
            msgs.append({"role": "system", "content": "\n\n".join(sys_parts)})
        msgs.extend(state.get_messages())
        return msgs

    while True:
        msgs = build_messages()
        log.info("Message sent to API: model=%s, messages=%d", settings.model, len(msgs))
        stream = client.chat.completions.create(
            model=settings.model,
            messages=msgs,
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=settings.max_tokens,
            stream=True,
        )

        content_buf: list[str] = []
        reasoning_buf: list[str] = []  # DeepSeek thinking-mode reasoning_content
        tool_calls_buf: dict[int, dict] = {}  # index -> {id, name, arguments}
        last_chunk = None
        last_finish_reason = None  # from last chunk that had choices (usage chunk has empty choices)
        chunk_count = 0
        chunks_with_choices = 0

        for chunk in stream:
            chunk_count += 1
            last_chunk = chunk
            if not chunk.choices:
                if is_log_debug():
                    log.debug("stream chunk #%d: empty choices", chunk_count)
                continue
            chunks_with_choices += 1
            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason is not None:
                last_finish_reason = choice.finish_reason
                if is_log_debug():
                    log.debug("stream chunk #%d: finish_reason=%r", chunk_count, choice.finish_reason)

            # Thinking-mode reasoning. Different backends emit this on different
            # field names; check the common variants. Whatever we collect will
            # be echoed back on the next request — the API rejects assistant
            # turns that drop reasoning_content in thinking mode.
            reasoning_chunk = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
                or getattr(delta, "thought", None)
                or getattr(delta, "thinking", None)
            )
            if reasoning_chunk:
                reasoning_buf.append(reasoning_chunk)
            # Diagnostic on first chunk only: dump field names of delta so we
            # can spot a non-standard reasoning field if it shows up.
            if chunk_count == 1 and is_log_debug():
                try:
                    log.debug("first-chunk delta fields: %s", list(delta.model_dump().keys()))
                except Exception:
                    log.debug("first-chunk delta dir: %s", [a for a in dir(delta) if not a.startswith("_")])

            if delta.content:
                content_buf.append(delta.content)
                if is_log_debug():
                    log.debug("model: %s", delta.content.replace("\n", "↵"))
                yield ("content_delta", {"delta": delta.content})

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buf:
                        tool_calls_buf[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    buf = tool_calls_buf[idx]
                    if tc.id:
                        buf["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            buf["name"] = tc.function.name
                        if tc.function.arguments:
                            buf["arguments"] += tc.function.arguments

        finish_reason = (
            last_chunk.choices[0].finish_reason
            if last_chunk and last_chunk.choices
            else last_finish_reason
        )
        full_content = "".join(content_buf)

        stream_summary = (
            "chunks=%d, with_choices=%d, content=%d chars, tool_calls=%d"
            % (chunk_count, chunks_with_choices, len(full_content), len(tool_calls_buf))
        )
        if is_log_debug():
            log.debug("Stream done: %s, finish_reason=%s", stream_summary, finish_reason)
        elif finish_reason is None:
            log.info("Stream summary: %s, finish_reason=%s", stream_summary, finish_reason)

        if full_content.strip():
            log.info("Content returned from API: %d chars", len(full_content.strip()))

        tool_calls_list = [
            tool_calls_buf[i]
            for i in sorted(tool_calls_buf.keys())
        ]
        tool_calls_formatted = [
            {
                "id": t["id"],
                "type": "function",
                "function": {"name": t["name"], "arguments": t["arguments"]},
            }
            for t in tool_calls_list
        ] if tool_calls_list else None

        # Always pass reasoning_content as a string (even empty) so the
        # field is round-tripped on the next API call. Thinking-mode backends
        # require it; non-thinking backends ignore the empty field.
        state.add_assistant_message(
            content=full_content or None,
            tool_calls=tool_calls_formatted,
            reasoning_content="".join(reasoning_buf),
        )

        if finish_reason == "stop":
            log.info("Model finished (stop)")
            yield ("done", {"text": full_content.strip()})
            return full_content.strip()

        if finish_reason == "tool_calls" and tool_calls_list:
            tool_results = []
            for t in tool_calls_list:
                name = t["name"]
                args_str = t["arguments"] or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}

                yield ("tool_call", {"name": name, "args": args, "id": t["id"]})
                log.info("Tool called: %s", name)
                result = execute(name, args)
                result_preview = result[:80] + "..." if len(result) > 80 else result
                log.info("Tool %s returned: %s", name, result_preview.replace("\n", " "))
                tool_results.append({"tool_call_id": t["id"], "content": result})
                yield ("tool_result", {"name": name, "result": result})

            state.add_tool_results(tool_results)
            log.debug("Tool results added, continuing ReAct loop")
            continue

        log.warning(
            "Unexpected finish_reason=%s, returning text (stream: %d chunks, %d with choices, %d content chars, tool_calls=%d)",
            finish_reason,
            chunk_count,
            chunks_with_choices,
            len(full_content),
            len(tool_calls_list),
        )
        yield ("done", {"text": full_content.strip()})
        return full_content.strip()


def run(user_message: str, settings: Settings) -> str:
    """
    Run one user turn through the ReAct loop. Returns the final assistant text.

    Flow:
    1. Add user message to state.
    2. Call OpenAI with messages + tools.
    3. If model returns text (finish_reason="stop"): return it.
    4. If model calls tools (finish_reason="tool_calls"): execute each,
       append results to state, go back to step 2.
    """
    state = ConversationState(system_prompt=DEFAULT_SYSTEM_PROMPT)
    state.add_user_message(user_message)

    client = create_client(settings)
    tools = get_tools()

    # Build messages for API: optional system, then conversation
    def build_messages() -> list[dict]:
        msgs = []
        if state.system_prompt:
            msgs.append({"role": "system", "content": state.system_prompt})
        msgs.extend(state.get_messages())
        return msgs

    while True:
        msgs = build_messages()
        log.info("Message sent to API: model=%s, messages=%d", settings.model, len(msgs))
        response = client.chat.completions.create(
            model=settings.model,
            messages=msgs,
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=settings.max_tokens,
        )

        choice = response.choices[0]
        msg = choice.message

        # Store assistant message (content + tool_calls if any)
        content = msg.content if msg.content else None
        if content and content.strip():
            log.info("Content returned from API: %d chars", len(content.strip()))
        tool_calls_raw = msg.tool_calls
        tool_calls = (
            [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (tool_calls_raw or [])
            ]
            if tool_calls_raw
            else None
        )
        reasoning = (
            getattr(msg, "reasoning_content", None)
            or getattr(msg, "reasoning", None)
            or getattr(msg, "thought", None)
            or getattr(msg, "thinking", None)
            or ""
        )
        state.add_assistant_message(
            content=content, tool_calls=tool_calls, reasoning_content=reasoning
        )

        if choice.finish_reason == "stop":
            # Model finished with text; return it
            return (msg.content or "").strip()

        if choice.finish_reason == "tool_calls" and tool_calls_raw:
            # Execute each tool and append results
            tool_results = []
            for tc in tool_calls_raw:
                name = tc.function.name
                args_str = tc.function.arguments or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}

                log.info("Tool called: %s", name)
                result = execute(name, args)
                tool_results.append({"tool_call_id": tc.id, "content": result})

            state.add_tool_results(tool_results)
            continue

        # finish_reason: length, content_filter, etc. — return what we have
        return (msg.content or "").strip()

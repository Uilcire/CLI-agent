"""ReAct agent loop: call model, execute tools, repeat until done."""

import json
from typing import Generator

from openai import OpenAI

from agent.config.settings import Settings
from agent.core.state import ConversationState
from agent.logger import get_logger
from agent.tools.registry import execute, get_tools

log = get_logger(__name__)

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
        state = ConversationState(
            system_prompt=(
                "You are a helpful cli code assistant.\n\n"
                "For deletions: When the user confirms they want to delete (e.g. 'yes', 'delete it', 'go ahead'), "
                "call delete_file or delete_dir directly. Do not ask for explicit text formats like 'DELETE ./path'. "
                "A confirmation dialog will automatically pop up when permission has not been granted this session."
            )
        )
    state.add_user_message(user_message)

    client = OpenAI(api_key=settings.api_key)
    tools = get_tools()
    log.debug("ReAct loop started, messages=%d", len(state.get_messages()))

    def build_messages() -> list[dict]:
        msgs = []
        if state.system_prompt:
            msgs.append({"role": "system", "content": state.system_prompt})
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
        tool_calls_buf: dict[int, dict] = {}  # index -> {id, name, arguments}
        last_chunk = None

        for chunk in stream:
            last_chunk = chunk
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content_buf.append(delta.content)
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
            else None
        )
        full_content = "".join(content_buf)
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

        state.add_assistant_message(
            content=full_content or None,
            tool_calls=tool_calls_formatted,
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

        log.warning("Unexpected finish_reason=%s, returning text", finish_reason)
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
    state = ConversationState(
        system_prompt=(
            "You are a helpful cli code assistant.\n\n"
            "For deletions: When the user confirms they want to delete (e.g. 'yes', 'delete it', 'go ahead'), "
            "call delete_file or delete_dir directly. Do not ask for explicit text formats like 'DELETE ./path'. "
            "A confirmation dialog will automatically pop up when permission has not been granted this session."
        )
    )
    state.add_user_message(user_message)

    client = OpenAI(api_key=settings.api_key)
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
        state.add_assistant_message(content=content, tool_calls=tool_calls)

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

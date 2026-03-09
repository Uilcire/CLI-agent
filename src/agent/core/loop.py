"""ReAct agent loop: call model, execute tools, repeat until done."""

import json

from openai import OpenAI

from agent.config.settings import Settings
from agent.core.state import ConversationState
from agent.tools.registry import execute, get_tools


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
    state = ConversationState(system_prompt="You are a helpful cli code assistant.")
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
        response = client.chat.completions.create(
            model=settings.model,
            messages=build_messages(),
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=settings.max_tokens,
        )

        choice = response.choices[0]
        msg = choice.message

        # Store assistant message (content + tool_calls if any)
        content = msg.content if msg.content else None
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

                result = execute(name, args)
                tool_results.append({"tool_call_id": tc.id, "content": result})

            state.add_tool_results(tool_results)
            continue

        # finish_reason: length, content_filter, etc. — return what we have
        return (msg.content or "").strip()

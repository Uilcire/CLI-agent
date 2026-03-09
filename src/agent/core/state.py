"""Conversation state: holds the message history for the API."""


class ConversationState:
    """
    Holds the list of messages (user, assistant, tool) for OpenAI chat completions.

    Message format follows OpenAI API:
    - user: {"role": "user", "content": str}
    - assistant: {"role": "assistant", "content": str | None, "tool_calls": [...]}
    - tool: {"role": "tool", "tool_call_id": str, "content": str}
    """

    def __init__(self, system_prompt: str | None = None) -> None:
        """
        Initialize empty conversation.

        system_prompt is stored separately; OpenAI passes it as a system message
        or we inject it at call time.
        """
        self._messages: list[dict] = []
        self._system_prompt = system_prompt

    def add_user_message(self, text: str) -> None:
        """
        Append a user text message.

        OpenAI expects content as a plain string for user messages.
        """
        self._messages.append({"role": "user", "content": text})

    def add_assistant_message(self, content: str | None, tool_calls: list | None = None) -> None:
        """
        Append an assistant message (with optional tool_calls).

        When the model returns text only: content="...", tool_calls=None.
        When the model calls tools: content may be None, tool_calls=[...].
        """
        msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)

    def add_tool_results(self, tool_results: list[dict]) -> None:
        """
        Append tool result messages.

        Each dict must have "tool_call_id" and "content".
        OpenAI expects one message per tool call.
        """
        for tr in tool_results:
            self._messages.append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "content": tr["content"],
            })

    def get_messages(self) -> list[dict]:
        """Return the message list for the API."""
        return self._messages

    @property
    def system_prompt(self) -> str | None:
        """System instruction for the model (optional)."""
        return self._system_prompt

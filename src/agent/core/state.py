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
        self._transient_system_suffix: str | None = None
        self.activated_skills: set[str] = set()

    def set_transient_system_suffix(self, suffix: str | None) -> None:
        """Append ``suffix`` to the system prompt for exactly one upcoming turn.

        ``consume_transient_system_suffix`` returns and clears it. Used by the
        memory subsystem to inject per-turn retrieved context without
        polluting conversation history.
        """
        self._transient_system_suffix = suffix or None

    def consume_transient_system_suffix(self) -> str | None:
        suffix = self._transient_system_suffix
        self._transient_system_suffix = None
        return suffix

    def add_user_message(self, text: str) -> None:
        """
        Append a user text message.

        OpenAI expects content as a plain string for user messages.
        """
        self._messages.append({"role": "user", "content": text})

    def add_assistant_message(
        self,
        content: str | None,
        tool_calls: list | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        """
        Append an assistant message (with optional tool_calls).

        When the model returns text only: content="...", tool_calls=None.
        When the model calls tools: content may be None, tool_calls=[...].
        reasoning_content is DeepSeek thinking-mode chain-of-thought; the API
        requires it to be round-tripped on subsequent multi-turn requests.
        """
        msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        # Thinking-mode backends (DeepSeek, ByteDance GPT) require this field
        # to be present on every assistant message — even empty. Storing as
        # falsy `None` previously caused 400 "must be passed back to the API".
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
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

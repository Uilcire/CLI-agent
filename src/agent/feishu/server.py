"""
Feishu bot — long-connection (WebSocket) mode.

No public IP or domain needed. The bot connects outbound to Feishu and
receives events over a persistent WebSocket.

Required env vars:
    FEISHU_APP_ID     — your Feishu app ID
    FEISHU_APP_SECRET — your Feishu app secret

Run:
    uv run feishu-bot
    # or
    uv run python -m agent.feishu.server
"""

import json
import os
import threading

import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.dispatcher_handler import (
    P2ImChatAccessEventBotP2pChatEnteredV1,
    P2ImMessageMessageReadV1,
)

from agent.config.settings import load_settings
from agent.core.loop import DEFAULT_SYSTEM_PROMPT, run_streaming
from agent.core.state import ConversationState
from agent.feishu.client import FeishuClient

load_dotenv()

# Per-user conversation state, keyed by open_id.
_sessions: dict[str, ConversationState] = {}
_session_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()

FEISHU_PREAMBLE = (
    "You are a helpful assistant talking to a user via Feishu (Lark) chat. "
    "Keep your replies concise and friendly. "
    "Do not use heavy Markdown — Feishu text messages render plain text."
)
FEISHU_SYSTEM_PROMPT = f"{FEISHU_PREAMBLE}\n\n{DEFAULT_SYSTEM_PROMPT}"


def _get_session(open_id: str) -> tuple[ConversationState, threading.Lock]:
    with _global_lock:
        if open_id not in _sessions:
            _sessions[open_id] = ConversationState(system_prompt=FEISHU_SYSTEM_PROMPT)
            _session_locks[open_id] = threading.Lock()
        return _sessions[open_id], _session_locks[open_id]


def _handle_message(data: P2ImMessageReceiveV1, client: FeishuClient) -> None:
    """Run the agent and reply to the user."""
    message = data.event.message
    sender = data.event.sender

    if message.message_type != "text":
        client.reply_text(message.message_id, "Sorry, I only understand text messages right now.")
        return

    try:
        text = json.loads(message.content).get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = (message.content or "").strip()

    if not text:
        return

    open_id = sender.sender_id.open_id
    state, lock = _get_session(open_id)
    settings = load_settings()

    with lock:
        reply_parts: list[str] = []
        try:
            for event_type, event_data in run_streaming(text, settings, state):
                if event_type == "content_delta":
                    reply_parts.append(event_data.get("delta", ""))
        except Exception as exc:
            client.reply_text(message.message_id, f"Agent error: {exc}")
            return

        reply = "".join(reply_parts).strip() or "(no response)"
        client.reply_text(message.message_id, reply)


def main() -> None:
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env")

    feishu_client = FeishuClient(app_id, app_secret)

    def on_message(data: P2ImMessageReceiveV1) -> None:
        # Handle in a background thread so the SDK event loop isn't blocked.
        thread = threading.Thread(
            target=_handle_message, args=(data, feishu_client), daemon=True
        )
        thread.start()

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(lambda _: None)
        .register_p2_im_message_message_read_v1(lambda _: None)
        .register_p2_im_message_reaction_created_v1(lambda _: None)
        .register_p2_im_message_reaction_deleted_v1(lambda _: None)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    print(f"Starting Feishu bot (long-connection mode) with app_id={app_id}")
    print("No public IP needed — connecting to Feishu via WebSocket...")
    ws_client.start()


if __name__ == "__main__":
    main()

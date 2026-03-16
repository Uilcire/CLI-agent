"""Feishu (Lark) API client: token management and message sending."""

import time
import requests

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_REPLY_URL = "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


class FeishuClient:
    """Thin wrapper around Feishu REST APIs."""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: str = ""
        self._token_expiry: float = 0.0

    def _get_token(self) -> str:
        """Return a valid tenant_access_token, refreshing if needed."""
        if time.time() < self._token_expiry - 60:
            return self._token

        resp = requests.post(
            _TOKEN_URL,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get Feishu token: {data}")

        self._token = data["tenant_access_token"]
        self._token_expiry = time.time() + data.get("expire", 7200)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def reply_text(self, message_id: str, text: str) -> dict:
        """Reply to a specific message with plain text."""
        url = _REPLY_URL.format(message_id=message_id)
        payload = {
            "msg_type": "text",
            "content": f'{{"text": {_json_str(text)}}}',
        }
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def send_text(self, receive_id: str, receive_id_type: str, text: str) -> dict:
        """Send a text message to a chat or user."""
        params = {"receive_id_type": receive_id_type}
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": f'{{"text": {_json_str(text)}}}',
        }
        resp = requests.post(
            _SEND_URL, json=payload, headers=self._headers(), params=params, timeout=15
        )
        resp.raise_for_status()
        return resp.json()


def _json_str(text: str) -> str:
    """Escape a string for embedding as a JSON string value (with surrounding quotes)."""
    import json
    return json.dumps(text)

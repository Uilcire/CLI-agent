"""TCP log server: receives pickled log records and prints them."""

import logging
import os
import pickle
import socket
import struct
import sys
from datetime import datetime


def main() -> None:
    host = ""
    port = int(os.environ.get("LOG_SERVER_PORT", "9999"))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(
                f"Port {port} is already in use. Try LOG_SERVER_PORT=9998 uv run log-server",
                file=sys.stderr,
            )
        raise
    server.listen(5)
    print(f"Log server listening on port {port}", file=sys.stderr)

    while True:
        client, _ = server.accept()
        try:
            while True:
                raw_len = client.recv(4)
                if not raw_len:
                    break
                if len(raw_len) < 4:
                    break
                msg_len = struct.unpack(">L", raw_len)[0]
                data = b""
                while len(data) < msg_len:
                    chunk = client.recv(min(msg_len - len(data), 65536))
                    if not chunk:
                        break
                    data += chunk
                if len(data) < msg_len:
                    break
                record_dict = pickle.loads(data)
                record = logging.makeLogRecord(record_dict)
                level = record.levelname
                ts_str = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
                msg = record.getMessage()
                # Bold blue for level; bold light blue for message prefix before ": "
                # Skip highlighting for debug/dispatch messages
                if ": " in msg and not msg.startswith("Dispatching tool"):
                    prefix, rest = msg.split(": ", 1)
                    msg_formatted = f"\033[1;96m{prefix}\033[0m: {rest}"
                else:
                    msg_formatted = msg
                print(f"\033[1;34m[{level}]\033[0m {ts_str} — {msg_formatted}")
        except (ConnectionResetError, EOFError, pickle.UnpicklingError):
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

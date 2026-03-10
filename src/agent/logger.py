"""Socket-based logging setup. Sends log records to log_server.py on port 9999."""

import logging
import os
from logging.handlers import SocketHandler


class SilentSocketHandler(SocketHandler):
    """SocketHandler that silently ignores connection failures (no crash, no stderr)."""

    def handleError(self, record: logging.LogRecord) -> None:
        """Suppress errors when log server is not running."""
        pass


def get_logger(name: str) -> logging.Logger:
    """Return a logger with SocketHandler pointing to localhost (port from LOG_SERVER_PORT).

    Falls back gracefully if the log server is not running (no crash).
    Log level defaults to DEBUG, configurable via LOG_LEVEL env var.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(_get_log_level())
    port = int(os.environ.get("LOG_SERVER_PORT", "9999"))
    handler = SilentSocketHandler("localhost", port)
    logger.addHandler(handler)
    return logger


def _get_log_level() -> int:
    level_name = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    return getattr(logging, level_name, logging.DEBUG)

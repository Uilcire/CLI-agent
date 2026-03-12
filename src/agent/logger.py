"""Socket-based logging setup. Sends log records to log_server.py on port 9999."""

import logging
import os
from logging.handlers import SocketHandler


class SilentSocketHandler(SocketHandler):
    """SocketHandler that silently ignores connection failures (no crash, no stderr).

    Overrides emit() to close the socket after each send. This forces the kernel
    to flush TCP send buffers immediately instead of holding data until process exit,
    fixing the "logs only appear after quitting" behavior.
    """

    def handleError(self, record: logging.LogRecord) -> None:
        """Suppress errors when log server is not running."""
        pass

    def emit(self, record: logging.LogRecord) -> None:
        """Send record and close socket so data flushes immediately."""
        try:
            s = self.makePickle(record)
            self.send(s)
        except Exception:
            self.handleError(record)
        finally:
            # Close socket after each emit so TCP buffers flush immediately
            self.close()
            self.sock = None


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


def is_log_debug() -> bool:
    """True if LOG_DEBUG=true/1/yes. Enables streaming model responses to logs."""
    v = (os.environ.get("LOG_DEBUG") or "").strip().lower()
    return v in ("true", "1", "yes")

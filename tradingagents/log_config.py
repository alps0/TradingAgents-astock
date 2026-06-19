"""Centralised logging configuration for TradingAgents-Astock.

Call ``setup_logging()`` once at program start (CLI, Web UI, or script).
It configures the root logger with a consistent format and sane defaults.

Environment variables:
  TRADINGAGENTS_LOG_LEVEL  — "DEBUG", "INFO", "WARNING" (default), "ERROR"
  TRADINGAGENTS_LOG_FILE   — optional file path to also write logs to
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that are too noisy at INFO level
_NOISY_LOGGERS = [
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "werkzeug",
    "asyncio",
    "multipart",
    "watchfiles",
    "langchain_core",
    "openai",
    "http11",
]


def setup_logging(level: str | None = None) -> None:
    """Initialise the root logger with a consistent format.

    Safe to call multiple times — subsequent calls are no-ops if the root
    logger already has handlers configured (prevents duplicate output when
    Streamlit hot-reloads).
    """
    root = logging.getLogger()

    # Prevent duplicate handlers on Streamlit hot-reload
    if root.handlers:
        return

    log_level = (level or os.getenv("TRADINGAGENTS_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=log_level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        stream=sys.stderr,
        force=False,
    )
    root.setLevel(log_level)

    # Silence noisy third-party loggers
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Optional file logging
    log_file = os.getenv("TRADINGAGENTS_LOG_FILE", "").strip()
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)

    logger = logging.getLogger(__name__)
    logger.debug("Logging initialised at %s level", log_level)

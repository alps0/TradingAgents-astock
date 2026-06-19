"""Manage analysis history by scanning existing log files."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


def _results_dir() -> Path:
    return Path.home() / ".tradingagents" / "logs"


def get_history() -> list[dict[str, str]]:
    """Scan saved analysis logs and return a sorted list (newest first).

    Each entry: {"ticker": "300750", "date": "2026-05-12", "path": "/abs/path/...json"}
    """
    root = _results_dir()
    if not root.exists():
        return []

    entries: list[dict[str, str]] = []
    for log_file in root.rglob("full_states_log_*.json"):
        match = re.search(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$", log_file.name)
        if not match:
            continue
        date = match.group(1)
        ticker = log_file.parent.parent.name
        entries.append({"ticker": ticker, "date": date, "path": str(log_file)})

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def load_analysis(path: str) -> dict[str, Any]:
    """Load a saved analysis JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def delete_history(path: str) -> bool:
    """Delete an analysis record by removing its entire date directory.

    Each analysis is stored in a directory like:
        ~/.tradingagents/logs/<ticker>/<date>/
    This removes the whole <date> directory (including all log files within).

    Returns True on success, False on failure.
    """
    log_path = Path(path)
    if not log_path.exists():
        return False

    # Safety: only allow deletion under the results directory
    try:
        log_path.resolve().relative_to(_results_dir().resolve())
    except ValueError:
        return False

    # Remove the date directory (parent of the log file)
    date_dir = log_path.parent
    try:
        shutil.rmtree(date_dir)
        return True
    except OSError:
        return False


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the short signal (Buy/Sell/Hold) from a final state dict."""
    import re

    for field in (
        "investment_plan",
        "trader_investment_decision",
        "final_trade_decision",
    ):
        text = state.get(field, "")
        if not text:
            continue
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        for keyword in ("BUY", "SELL", "HOLD"):
            if keyword in cleaned.upper():
                return keyword.capitalize()
    return "N/A"

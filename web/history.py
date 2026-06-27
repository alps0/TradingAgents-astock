"""Manage analysis history by scanning existing log files."""

from __future__ import annotations

import importlib.util
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


def _fallback_parse_rating(text: str, default: str = "Hold") -> str:
    """Lightweight fallback parser used when the packaged module is unavailable."""
    rating_map = {name.lower(): name for name in ("Buy", "Overweight", "Hold", "Underweight", "Sell")}
    pattern = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)

    for line in str(text).splitlines():
        match = pattern.search(line)
        if match and match.group(1).lower() in rating_map:
            return rating_map[match.group(1).lower()]

    for line in str(text).splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in rating_map:
                return rating_map[clean]

    return default


def _load_parse_rating():
    """Load the rating parser without importing the full agents package."""
    module_path = Path(__file__).resolve().parents[1] / "tradingagents" / "agents" / "utils" / "rating.py"
    try:
        spec = importlib.util.spec_from_file_location("tradingagents_agents_utils_rating", module_path)
        if spec is None or spec.loader is None:
            return _fallback_parse_rating

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "parse_rating", _fallback_parse_rating)
    except (FileNotFoundError, ImportError, OSError, AttributeError):
        return _fallback_parse_rating


_PARSE_RATING = None


def _get_parse_rating():
    global _PARSE_RATING
    if _PARSE_RATING is None:
        _PARSE_RATING = _load_parse_rating()
    return _PARSE_RATING


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the portfolio rating from a final state dict.

    The live analysis UI uses the 5-tier rating from the Portfolio Manager's
    structured output. History view should preserve the same rating, rather than
    falling back to a coarse Buy/Sell/Hold keyword search.
    """
    parse_rating = _get_parse_rating()

    for field in (
        "final_trade_decision",
        "investment_plan",
        "trader_investment_decision",
    ):
        text = state.get(field, "")
        if not text:
            continue
        cleaned = re.sub(r"<think>.*?</think>", "", str(text), flags=re.DOTALL)
        parsed = parse_rating(cleaned, default="Hold")
        if parsed and parsed != "Hold":
            return parsed

    return "Hold"

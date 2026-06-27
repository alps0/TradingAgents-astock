import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.time_utils import get_report_now
from web.history import extract_signal
from web.session_utils import clear_large_session_state


def test_extract_signal_prefers_explicit_rating() -> None:
    state = {
        "final_trade_decision": "**Rating**: Underweight\nTrim exposure.",
    }

    assert extract_signal(state) == "Underweight"


def test_get_report_now_uses_configured_timezone(monkeypatch) -> None:
    monkeypatch.setenv("REPORT_TIMEZONE", "Asia/Shanghai")

    dt = get_report_now()

    assert dt.tzinfo is not None
    assert str(dt.tzinfo) == "Asia/Shanghai"


def test_extract_signal_falls_back_when_parser_is_unavailable(monkeypatch) -> None:
    import web.history as history

    monkeypatch.setattr(history, "_PARSE_RATING", None)
    state = {
        "final_trade_decision": "**Rating**: Underweight\nTrim exposure.",
    }

    assert history.extract_signal(state) == "Underweight"


def test_clear_large_session_state_supports_mapping_like_objects() -> None:
    class FakeSessionState:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data

        def keys(self):
            return self._data.keys()

        def pop(self, key: str, default=None):
            return self._data.pop(key, default)

        def __contains__(self, key: str) -> bool:
            return key in self._data

    state = FakeSessionState({"_pdf_a": b"x", "tracker": object(), "keep": "ok"})

    clear_large_session_state(state)

    assert "_pdf_a" not in state
    assert "tracker" not in state
    assert "keep" in state

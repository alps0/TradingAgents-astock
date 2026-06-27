import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.session_utils import clear_large_session_state


def test_clear_large_session_state_removes_pdf_cache_and_tracker() -> None:
    session_state: dict[str, Any] = {
        "tracker": object(),
        "foo": "bar",
        "_pdf_old": b"old-pdf",
        "_pdf_current": b"current-pdf",
    }

    clear_large_session_state(session_state, keep_keys={"_pdf_current"})

    assert "tracker" not in session_state
    assert "foo" in session_state
    assert "_pdf_old" not in session_state
    assert session_state["_pdf_current"] == b"current-pdf"

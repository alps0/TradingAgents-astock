from __future__ import annotations

from typing import Any


def clear_large_session_state(session_state: Any, keep_keys: set[str] | None = None) -> None:
    """Prune large cached objects from Streamlit session state.

    This is used to avoid retaining large PDF bytes or full report payloads in
    memory across page switches and history-view actions.

    The function accepts both plain dicts and Streamlit's SessionStateProxy.
    """
    keep = set(keep_keys or set())
    keys_to_remove: list[str] = []
    for key in list(session_state.keys()):
        if key in keep:
            continue
        # Only prune large cached objects (PDF bytes cached under "_pdf_*" keys).
        # Do NOT touch "viewing_history" or "tracker" here — those are
        # interactive-state keys whose lifecycle is managed by app.py's state
        # machine. Clearing them on every rerun (this function is called at the
        # top of app.py) would discard the user's "click history entry" intent
        # before the main state machine can read it, making history buttons look
        # unresponsive (issue: history-click-no-response).
        if key.startswith("_pdf_"):
            keys_to_remove.append(key)
            continue
    for key in keys_to_remove:
        try:
            session_state.pop(key, None)
        except TypeError:
            if key in session_state:
                del session_state[key]

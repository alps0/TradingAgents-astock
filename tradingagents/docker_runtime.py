from __future__ import annotations

import os
from pathlib import Path


def prepare_runtime_directories(home_dir: str | os.PathLike[str] | None = None, user_name: str | None = None) -> None:
    """Create runtime directories and ensure they are writable for the app user.

    This helps when the container mounts a host path into ~/.tradingagents and the
    host-side directory is created with root ownership or different permissions.
    """
    home_path = Path(home_dir or os.path.expanduser("~"))
    app_home = home_path.resolve()

    dirs_to_create = [
        app_home / ".tradingagents",
        app_home / ".tradingagents" / "cache",
        app_home / ".tradingagents" / "logs",
        app_home / ".tradingagents" / "memory",
        app_home / ".tradingagents" / "licenses",
        app_home / ".streamlit",
    ]

    for directory in dirs_to_create:
        directory.mkdir(parents=True, exist_ok=True)

    try:
        os.chmod(app_home, 0o755)
    except PermissionError:
        pass

    for directory in dirs_to_create:
        try:
            os.chmod(directory, 0o777)
        except PermissionError:
            pass

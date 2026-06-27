"""Launch the TradingAgents web UI via `tradingagents-web` command."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tradingagents.docker_runtime import prepare_runtime_directories


def main() -> None:
    home_dir = os.environ.get("HOME", os.path.expanduser("~"))
    prepare_runtime_directories(home_dir, user_name=os.environ.get("USER"))

    app_path = Path(__file__).parent / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


if __name__ == "__main__":
    main()

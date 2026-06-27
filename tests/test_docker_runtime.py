import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.docker_runtime import prepare_runtime_directories


def test_prepare_runtime_directories_creates_expected_paths(tmp_path: Path) -> None:
    home_dir = tmp_path / "home" / "appuser"

    prepare_runtime_directories(home_dir, user_name="appuser")

    expected_paths = [
        home_dir / ".tradingagents",
        home_dir / ".tradingagents" / "cache",
        home_dir / ".tradingagents" / "logs",
        home_dir / ".tradingagents" / "memory",
        home_dir / ".streamlit",
    ]

    for path in expected_paths:
        assert path.exists()
        assert path.is_dir()

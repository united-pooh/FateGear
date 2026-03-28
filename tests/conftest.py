from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LOG_ROOT = ROOT / "log"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_sessionstart(session) -> None:
    for subdir_name in ("scene", "story"):
        subdir = LOG_ROOT / subdir_name
        subdir.mkdir(parents=True, exist_ok=True)
        for log_file in subdir.glob("*.log"):
            log_file.unlink()

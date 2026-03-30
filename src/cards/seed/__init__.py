from __future__ import annotations

from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
BASE_SKILLS_PATH = SEED_DIR / "base_skills.json"
BRANCH_SKILLS_PATH = SEED_DIR / "branch_skills.json"

__all__ = [
    "BASE_SKILLS_PATH",
    "BRANCH_SKILLS_PATH",
    "SEED_DIR",
]

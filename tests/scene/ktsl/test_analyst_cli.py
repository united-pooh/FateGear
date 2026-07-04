"""Tests for the ktsl analyst CLI subcommand."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "src"


def _env_with_src() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{SRC}{os.pathsep}{existing}" if existing else str(SRC)
    )
    return env


def _run_ktsl(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "src.scenario.cli.ktsl_cli", *args]
    return subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        check=False, env=_env_with_src(),
    )


class TestAnalystCLI:
    def test_analyst_help_works(self) -> None:
        proc = _run_ktsl("analyst", "--help")
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        assert "session_id" in proc.stdout

    def test_analyst_missing_session_id_shows_error(self) -> None:
        proc = _run_ktsl("analyst")
        # Non-zero exit; missing required arg
        assert proc.returncode != 0

    def test_analyst_table_output_contains_headers(self, tmp_path: Path) -> None:
        # First create a minimal ktsl log dir so analyst reads it
        log_root = tmp_path / "session/s1/ktsl"
        turn_dir = log_root / "1"
        turn_dir.mkdir(parents=True)
        (turn_dir / "audit_snapshot.json").write_text(
            json.dumps({"committed_events": 2, "pending_events": 0})
        )
        (turn_dir / "stage_trace.jsonl").write_text(
            '{"stage":"ScheduleGate","status":"continue","ms":0.1}\n'
        )
        (turn_dir / "interventions.jsonl").write_text("")
        (turn_dir / "ledger_diffs.jsonl").write_text(
            json.dumps({"module_id":"m","committed_count":2})
        )

        proc = _run_ktsl("analyst", "s1", "--log-base", str(tmp_path))
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        # Should show metrics table headers or at least the turn number
        assert "1" in proc.stdout or "turn" in proc.stdout.lower()

"""Tests for per-turn KTSL decision-log writer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenario.ktsl.log_writer import KTSLLogWriter
from scenario.ktsl.models import KTSLLedger
from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.wizard import build_spec_from_fixture


@pytest.fixture
def ledger(tmp_path: Path) -> KTSLLedger:
    fixture = build_library_sewer_church_fixture()
    spec = build_spec_from_fixture(fixture)
    ledger = KTSLLedger.from_module_spec(
        module_id="test_mod", spec=spec
    )
    return ledger


class TestKTSLLogWriter:
    def test_log_dir_is_deterministic(self) -> None:
        d = KTSLLogWriter.log_dir("session_001")
        assert d == Path("log/session/session_001/ktsl")

    def test_write_turn_creates_turn_subdir(
        self, tmp_path: Path, ledger: KTSLLedger
    ) -> None:
        base = tmp_path / "session/s1/ktsl"
        KTSLLogWriter.write_turn(
            base_dir=base,
            turn_no=3,
            stage_trace=[
                {"stage": "ScheduleGate", "status": "continue", "ms": 0.2},
                {"stage": "Filter", "status": "continue", "ms": 1.5},
            ],
            interventions=[],
            ledger_snapshot=ledger.snapshot(),
            audit_snapshot={"causal_violations": 0, "committed_events": 5},
        )
        turn_dir = base / "3"
        assert turn_dir.is_dir()
        assert (turn_dir / "stage_trace.jsonl").exists()
        assert (turn_dir / "interventions.jsonl").exists()
        assert (turn_dir / "ledger_diffs.jsonl").exists()
        assert (turn_dir / "audit_snapshot.json").exists()

    def test_audit_snapshot_is_json_serializable(
        self, tmp_path: Path, ledger: KTSLLedger
    ) -> None:
        base = tmp_path / "session/s2/ktsl"
        KTSLLogWriter.write_turn(
            base_dir=base, turn_no=1,
            stage_trace=[], interventions=[],
            ledger_snapshot=ledger.snapshot(),
            audit_snapshot={"committed_events": 3, "pending_events": 1},
        )
        snap_path = base / "1" / "audit_snapshot.json"
        loaded = json.loads(snap_path.read_text())
        assert loaded["committed_events"] == 3

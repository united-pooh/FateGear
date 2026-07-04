"""Per-turn KTSL decision bundle writer.

Each turn writes one subdirectory under ``log/session/<session_id>/ktsl/<turn_no>/``
containing::

    stage_trace.jsonl          # one JSON object per stage run
    interventions.jsonl        # one JSON object per BLOCK/REDACT/WAIT intervention
    ledger_diffs.jsonl         # committed_events[] + updated_knowledge[]
    audit_snapshot.json        # MetricSummary-equivalent dict at turn end
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KTSLLogWriter:
    """Stateless writer for KTSL decision logs."""

    @staticmethod
    def log_dir(session_id: str) -> Path:
        return Path("log/session") / session_id / "ktsl"

    @staticmethod
    def write_turn(
        *,
        base_dir: Path,
        turn_no: int,
        stage_trace: list[dict[str, Any]],
        interventions: list[dict[str, Any]],
        ledger_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
    ) -> Path:
        """Write a single turn's decision bundle. Returns the turn directory."""
        turn_dir = base_dir / str(turn_no)
        turn_dir.mkdir(parents=True, exist_ok=True)

        # stage_trace.jsonl
        with (turn_dir / "stage_trace.jsonl").open("w", encoding="utf-8") as fh:
            for entry in stage_trace:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # interventions.jsonl
        with (turn_dir / "interventions.jsonl").open("w", encoding="utf-8") as fh:
            for entry in interventions:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # ledger_diffs.jsonl
        with (turn_dir / "ledger_diffs.jsonl").open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(ledger_snapshot, ensure_ascii=False) + "\n")

        # audit_snapshot.json
        with (turn_dir / "audit_snapshot.json").open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(audit_snapshot, ensure_ascii=False))

        return turn_dir

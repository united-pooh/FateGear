"""Terminal renderer for KTSL analyst output (tables + JSON)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AnalystRenderer:
    """Render KTSL decision bundles from log/session/<id>/ktsl/."""

    def __init__(self, log_base: Path) -> None:
        self._log_base = Path(log_base)

    def render_table(self, session_id: str, *, turn: int | None = None) -> str:
        """Render a per-turn metrics table for a session."""
        session_dir = self._log_base / "session" / session_id / "ktsl"
        if not session_dir.exists():
            return f"[No KTSL logs found at {session_dir}]"

        turn_dirs = sorted(
            d for d in session_dir.iterdir() if d.is_dir() and d.name.isdigit()
        )
        if turn is not None:
            turn_dirs = [d for d in turn_dirs if int(d.name) == turn]

        if not turn_dirs:
            return f"[No turn data in {session_dir}]"

        lines = [f"# KTSL Analyst — {session_id}", ""]
        lines.append(f"| {'turn':>4} | {'committed':>9} | {'pending':>7} | {'info_count':>10} |")
        lines.append(f"|{'—'*6}|{'—'*11}|{'—'*9}|{'—'*12}|")

        for td in turn_dirs:
            audit_path = td / "audit_snapshot.json"
            ledger_path = td / "ledger_diffs.jsonl"
            audit = self._load_json(audit_path) if audit_path.exists() else {}
            ledger: dict[str, Any] = {}
            if ledger_path.exists():
                try:
                    ledger = json.loads(ledger_path.read_text().strip().split("\n")[0])
                except Exception:
                    ledger = {}
            turn_no = td.name
            committed = audit.get("committed_events", "?")
            pending = audit.get("pending_events", "?")
            info_count = ledger.get("info_count", "?")
            lines.append(
                f"| {turn_no:>4} | {committed:>9} | {pending:>7} | {info_count:>10} |"
            )

        return "\n".join(lines)

    def render_focus(
        self, session_id: str, focus: str, *, turn: int | None = None
    ) -> str:
        """Render a focused view: causal / knowledge / interventions / wait / modes / metrics."""
        session_dir = self._log_base / "session" / session_id / "ktsl"
        if not session_dir.exists():
            return f"[No KTSL logs found at {session_dir}]"

        turn_dirs = sorted(
            (d for d in session_dir.iterdir() if d.is_dir() and d.name.isdigit()),
            key=lambda d: int(d.name),
        )
        if turn is not None:
            turn_dirs = [d for d in turn_dirs if int(d.name) == turn]

        lines: list[str] = []
        for td in turn_dirs:
            lines.append(f"### Turn {td.name} — focus: {focus}")
            if focus == "interventions":
                path = td / "interventions.jsonl"
                if path.exists() and path.read_text().strip():
                    for line in path.read_text().split("\n"):
                        lines.append(f"  - {line}")
                else:
                    lines.append("  (no interventions)")
            elif focus == "causal":
                path = td / "stage_trace.jsonl"
                if path.exists():
                    for line in path.read_text().split("\n"):
                        if "ScheduleGate" in line:
                            lines.append(f"  - {line}")
            elif focus == "metrics":
                path = td / "audit_snapshot.json"
                if path.exists():
                    data = self._load_json(path)
                    for k, v in data.items():
                        lines.append(f"  {k}: {v}")
            else:
                lines.append(f"  (focus '{focus}' not yet rendered)")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

"""KTSL Markdown report renderer.

Renders SessionReport / PublishReport / ValidateReport to Markdown strings
using pure Python f-string concatenation (zero additional dependencies).

The output is designed to be consumable by Pandoc, Obsidian, Notion, or any
standard Markdown viewer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .session_reports import (
    PublishReport,
    SessionReport,
    ValidateReport,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metric_rows(report: SessionReport) -> list[tuple[str, str]]:
    """Return (display_name, string_value) pairs for the six core metrics."""
    m = report.metrics
    return [
        ("Causal Violations", str(m.causal_violation_count)),
        ("Unauthorized Actions", str(m.unauthorized_action_count)),
        ("Public Payload Leaks", str(m.public_payload_leak_count)),
        ("Spotlight Max Gap (min)", str(m.spotlight_max_gap_minutes)),
        ("Declassification", f"{m.declassification_completeness:.2f}"),
        ("Retcons", str(m.retcon_count)),
    ]


def _severity_badge(severity: str) -> str:
    return {
        "error": "ERROR",
        "warning": "WARN",
        "info": "INFO",
    }.get(severity, severity.upper())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MarkdownRenderer:
    """Render KTSL reports to Markdown strings using pure f-string formatting."""

    # ------------------------------------------------------------------
    # Session Report
    # ------------------------------------------------------------------

    @staticmethod
    def render_session(report: SessionReport) -> str:
        """Render a full Session Report as a Markdown string."""
        lines: list[str] = []

        # Header
        lines.append("# KTSL Session Report")
        lines.append("")
        lines.append(f"**Module**: {report.fixture_title or report.fixture_id}")
        lines.append(f"**Fixture ID**: `{report.fixture_id}`")
        lines.append(f"**Session ID**: `{report.session_config.session_id}`" if report.session_config else "")
        lines.append(
            f"**KP**: {report.session_config.kp_name}" if report.session_config and report.session_config.kp_name else ""
        )
        lines.append(f"**Started**: {report.started_at}")
        lines.append(f"**Ended**: {report.ended_at}")
        lines.append("")

        # Metrics dashboard
        lines.append("## 📊 Metrics Dashboard")
        lines.append("")
        rows = _metric_rows(report)
        header = "| " + " | ".join(name for name, _ in rows) + " |"
        separator = "| " + " | ".join("---" for _ in rows) + " |"
        values = "| " + " | ".join(val for _, val in rows) + " |"
        lines.extend([header, separator, values, ""])

        # Totals line
        lines.append(
            f"**Totals**: events={report.total_events} · "
            f"committed={report.total_committed} · "
            f"blocked={report.total_blocked} · "
            f"overridden={report.total_overridden}"
        )
        lines.append("")

        # Barrier wait / drift info
        m = report.metrics
        lines.append(
            f"Barrier wait: {m.barrier_wait_minutes} min · "
            f"High-coupling drift: {m.high_coupling_time_drift_minutes} min"
        )
        lines.append("")

        # Violation Timeline
        lines.append("## ⚠️ Violation Timeline")
        lines.append("")
        if report.violation_timeline:
            for ve in report.violation_timeline:
                override_tag = " [OVERRIDDEN]" if ve.overridden else ""
                badge = _severity_badge(ve.severity)
                lines.append(
                    f"- **[{badge}]** Event #{ve.event_index:03d} · "
                    f"actor={ve.actor} · scene={ve.scene_id}{override_tag}"
                )
                lines.append(f"  - ID: `{ve.event_id}`")
                lines.append(f"  - Action: {ve.action_text}")
                lines.append(f"  - Metric: `{ve.metric}` — {ve.message}")
        else:
            lines.append("_No violations recorded._")
        lines.append("")

        # Character Knowledge Map
        lines.append("## 🗺️ Character Knowledge Map")
        lines.append("")
        if report.final_knowledge_map:
            for char_id, items in report.final_knowledge_map.items():
                lines.append(f"### {char_id}")
                lines.append("")
                if not items:
                    lines.append("_No knowledge recorded._")
                    lines.append("")
                    continue
                lines.append("| info_id | kind | sensitivity | content_summary | source |")
                lines.append("| --- | --- | --- | --- | --- |")
                for item in items:
                    leak_tag = " ⚠️LEAKED" if getattr(item, "leaked", False) else ""
                    summary = item.content_summary.replace("|", "\\|").replace("\n", " ")
                    if len(summary) > 120:
                        summary = summary[:117] + "…"
                    lines.append(
                        f"| `{item.info_id}` | {item.kind} | {item.sensitivity} "
                        f"| {summary}{leak_tag} | {item.source_event_id} |"
                    )
                lines.append("")
        else:
            lines.append("_No character knowledge recorded._")
            lines.append("")

        # Scene Timelines
        lines.append("## 🎬 Scene Timelines")
        lines.append("")
        if report.scene_timelines:
            for scene_id, events in report.scene_timelines.items():
                lines.append(f"### `{scene_id}`")
                lines.append("")
                if not events:
                    lines.append("_No events._")
                    lines.append("")
                    continue
                for ev in events:
                    info_part = (
                        f" → output: {', '.join(ev.output_info_ids)}"
                        if ev.output_info_ids
                        else ""
                    )
                    lines.append(
                        f"- #{ev.event_index:03d} [{ev.status}] {ev.actor}: "
                        f"{ev.action_text} @ {ev.time_minute}min{info_part}"
                    )
                lines.append("")
        else:
            lines.append("_No scene timelines available._")
            lines.append("")

        # Barrier States
        lines.append("## 🚧 Barrier States")
        lines.append("")
        if report.barrier_final_states:
            lines.append("| barrier_id | status | required_events | satisfied_events | required_info | satisfied_info |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for b in report.barrier_final_states:
                req_ev = ", ".join(b.required_event_ids) or "—"
                sat_ev = ", ".join(b.satisfied_event_ids) or "—"
                req_inf = ", ".join(b.required_info_ids) or "—"
                sat_inf = ", ".join(b.satisfied_info_ids) or "—"
                lines.append(
                    f"| `{b.barrier_id}` | {b.status} | {req_ev} | {sat_ev} | {req_inf} | {sat_inf} |"
                )
        else:
            lines.append("_No barriers configured._")
        lines.append("")

        # Coupling States
        lines.append("## 🔗 Coupling States")
        lines.append("")
        if report.coupling_final_states:
            lines.append("| coupling_id | source | target | mode | drift (min) | active |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for c in report.coupling_final_states:
                lines.append(
                    f"| `{c.coupling_id}` | {c.source_scene_id} | {c.target_scene_id} "
                    f"| {c.mode} | {c.drift_minutes} | {'✅' if c.active else '❌'} |"
                )
        else:
            lines.append("_No couplings configured._")
        lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"_Generated by KTSL toolchain · {_now_iso()}_")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Publish Report
    # ------------------------------------------------------------------

    @staticmethod
    def render_publish(report: PublishReport) -> str:
        """Render a full Publish Gate Report as a Markdown string."""
        lines: list[str] = []

        verdict = "✅ PASS" if report.overall_pass else "❌ FAIL"

        lines.append("# KTSL Publish Gate Report")
        lines.append("")
        lines.append(f"## {_verdict_badge(report.overall_pass)}")
        lines.append("")
        lines.append(f"**Module**: {report.fixture_title or report.fixture_id}")
        lines.append(f"**Fixture ID**: `{report.fixture_id}`")
        lines.append(f"**Criteria version**: {report.criteria_version}")
        lines.append(f"**Evaluated at**: {report.evaluated_at}")
        lines.append(f"**Verdict**: {verdict}")
        lines.append("")

        # Mode comparison table
        lines.append("## Mode Comparison")
        lines.append("")

        # Build column headers dynamically (metric × each mode, with threshold column)
        modes = [mr.mode for mr in report.per_mode]
        header_cols = ["Metric"] + [f"`{m}`" for m in modes] + ["Threshold"]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("| " + " | ".join("---" for _ in header_cols) + " |")

        # Use the first mode's metrics to get field names
        if report.per_mode:
            mr0 = report.per_mode[0]
            metric_fields = _publish_metric_rows(mr0.metrics)
        else:
            metric_fields = []

        for display_name, field_name in metric_fields:
            row: list[str] = [display_name]
            threshold_strs: list[str] = []
            for mr in report.per_mode:
                val = getattr(mr.metrics, field_name)
                if isinstance(val, float):
                    cell = f"{val:.2f}"
                else:
                    cell = str(val)
                if not mr.passed:
                    # Mark failing cells
                    cell = f"**{cell}**"
                row.append(cell)
                # Threshold for this mode
                thresh = report.thresholds.get(mr.mode)
                if thresh is not None:
                    t = _threshold_for(thresh, field_name)
                    threshold_strs.append(t or "—")
                else:
                    threshold_strs.append("—")
            # Show a single threshold column (the most restrictive one if they differ)
            row.append(" / ".join(threshold_strs) if threshold_strs else "—")
            lines.append("| " + " | ".join(row) + " |")

        # Verdict line
        verdict_row = ["Verdict"] + [
            ("✅ PASS" if mr.passed else "❌ FAIL") for mr in report.per_mode
        ] + [""]
        lines.append("| " + " | ".join(verdict_row) + " |")
        lines.append("")

        # Failures
        all_failures: list[tuple[str, str]] = []
        for mr in report.per_mode:
            for f in mr.failures:
                all_failures.append((mr.mode, f))
        lines.append("## Failures")
        lines.append("")
        if all_failures:
            for mode, f in all_failures:
                lines.append(f"- **`{mode}`**: {f}")
        else:
            lines.append("_No failures._")
        lines.append("")

        # Warnings
        all_warnings: list[tuple[str, str]] = []
        for mr in report.per_mode:
            for w in mr.warnings:
                all_warnings.append((mr.mode, w))
        lines.append("## Warnings")
        lines.append("")
        if all_warnings:
            for mode, w in all_warnings:
                lines.append(f"- **`{mode}`**: {w}")
        else:
            lines.append("_No warnings._")
        lines.append("")

        lines.append("---")
        lines.append(f"_Generated by KTSL toolchain · {_now_iso()}_")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Validate Report
    # ------------------------------------------------------------------

    @staticmethod
    def render_validate(report: ValidateReport) -> str:
        """Render a full Validate Report as a Markdown string."""
        lines: list[str] = []

        badge = "✅ PASS" if report.is_valid else "❌ FAIL"

        lines.append("# KTSL Validate Report")
        lines.append("")
        lines.append(f"## {badge}")
        lines.append("")
        lines.append(f"**Fixture ID**: `{report.fixture_id}`")
        lines.append(f"**Fixture Title**: {report.fixture_title or '—'}")
        lines.append(f"**Validated at**: {report.validated_at}")
        lines.append(f"**Is Valid**: {report.is_valid}")
        lines.append("")

        errors = [i for i in report.issues if i.level == "error"]
        warnings = [i for i in report.issues if i.level == "warning"]
        infos = [i for i in report.issues if i.level == "info"]

        lines.append(f"## Errors ({len(errors)})")
        lines.append("")
        if errors:
            for issue in errors:
                lines.append(f"- **[ERROR]** `{issue.code}`: {issue.message}")
                if issue.resource_id:
                    lines.append(f"  - Resource: `{issue.resource_id}`")
        else:
            lines.append("_No errors._")
        lines.append("")

        lines.append(f"## Warnings ({len(warnings)})")
        lines.append("")
        if warnings:
            for issue in warnings:
                lines.append(f"- **[WARN]** `{issue.code}`: {issue.message}")
                if issue.resource_id:
                    lines.append(f"  - Resource: `{issue.resource_id}`")
        else:
            lines.append("_No warnings._")
        lines.append("")

        if infos:
            lines.append(f"## Infos ({len(infos)})")
            lines.append("")
            for issue in infos:
                lines.append(f"- **[INFO]** `{issue.code}`: {issue.message}")
            lines.append("")

        # Summary line for exit code reference
        if errors:
            exit_code = 2
        elif warnings:
            exit_code = 1
        else:
            exit_code = 0
        lines.append(f"**Exit code**: `{exit_code}`")
        lines.append("")
        lines.append("---")
        lines.append(f"_Generated by KTSL toolchain · {_now_iso()}_")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def render_session(report: SessionReport) -> str:
    """Convenience wrapper around MarkdownRenderer.render_session."""
    return MarkdownRenderer.render_session(report)


def render_publish(report: PublishReport) -> str:
    """Convenience wrapper around MarkdownRenderer.render_publish."""
    return MarkdownRenderer.render_publish(report)


def render_validate(report: ValidateReport) -> str:
    """Convenience wrapper around MarkdownRenderer.render_validate."""
    return MarkdownRenderer.render_validate(report)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _verdict_badge(overall_pass: bool) -> str:
    return "Verdict: PASS" if overall_pass else "Verdict: FAIL"


def _publish_metric_rows(metrics: Any) -> list[tuple[str, str]]:
    """Return (display_name, field_name) pairs for publish report rows."""
    return [
        ("Causal Violations", "causal_violation_count"),
        ("Unauthorized Actions", "unauthorized_action_count"),
        ("Public Payload Leaks", "public_payload_leak_count"),
        ("Spotlight Max Gap (min)", "spotlight_max_gap_minutes"),
        ("Declassification", "declassification_completeness"),
        ("Retcons", "retcon_count"),
        ("High-Coupling Drift (min)", "high_coupling_time_drift_minutes"),
        ("Barrier Wait (min)", "barrier_wait_minutes"),
        ("Committed Events", "committed_event_count"),
        ("Blocked Events", "blocked_event_count"),
    ]


def _threshold_for(thresh: Any, field_name: str) -> str | None:
    """Map a MetricSummary field name to the matching ModeThresholds field value."""
    _FIELD_TO_THRESHOLD = {
        "causal_violation_count": "max_causal_violations",
        "unauthorized_action_count": "max_unauthorized_actions",
        "public_payload_leak_count": "max_public_payload_leaks",
        "spotlight_max_gap_minutes": "max_spotlight_gap_minutes",
        "declassification_completeness": "min_declassification_completeness",
        "retcon_count": "max_retcons",
        "high_coupling_time_drift_minutes": "max_high_coupling_drift_minutes",
    }
    t_field = _FIELD_TO_THRESHOLD.get(field_name)
    if t_field is None:
        return None
    val = getattr(thresh, t_field, None)
    if val is None:
        return None
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


__all__ = [
    "MarkdownRenderer",
    "render_session",
    "render_publish",
    "render_validate",
]

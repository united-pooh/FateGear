"""KTSL HTML report renderer (Jinja2 template engine).

Provides HTMLRenderer that loads local Jinja2 templates and renders
SessionReport / PublishReport / ValidateReport to complete HTML documents
with inline CSS (no external CDN dependency; works fully offline).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session_reports import (
    PublishReport,
    SessionReport,
    ValidateReport,
)

try:
    from jinja2 import Environment, FileSystemLoader, TemplateNotFound

    _JINJA2_AVAILABLE = True
except ImportError:  # pragma: no cover — graceful fallback
    _JINJA2_AVAILABLE = False


# ---------------------------------------------------------------------------
# Radar SVG generator (pure Python, no SVG library)
# ---------------------------------------------------------------------------

# 6 axes for the radar chart (Causal, Unauth, Leak, Spot, Decl, Retcon)
_RADAR_AXES = [
    ("Causal", "causal_violation_count", False),
    ("Unauth", "unauthorized_action_count", False),
    ("Leak", "public_payload_leak_count", False),
    ("Spot", "spotlight_max_gap_minutes", False),
    ("Decl", "declassification_completeness", True),  # inverted (higher is better)
    ("Retcon", "retcon_count", False),
]

# Maximum value used for normalization per axis (soft cap)
_RADAR_MAX: dict[str, float] = {
    "causal_violation_count": 5.0,
    "unauthorized_action_count": 5.0,
    "public_payload_leak_count": 5.0,
    "spotlight_max_gap_minutes": 60.0,
    "declassification_completeness": 1.0,
    "retcon_count": 5.0,
}

_RADAR_COLORS = {
    "baseline": "#9ca3af",
    "schedule_only": "#3b82f6",
    "ktsl_full": "#10b981",
}


def _polar(cx: float, cy: float, r: float, angle_rad: float) -> tuple[float, float]:
    """Convert polar coords to cartesian, with angle 0 at the top."""
    return cx - r * __import__("math").sin(angle_rad), cy - r * __import__("math").cos(angle_rad)


def _build_radar_svg(
    per_mode_results: list[Any],
    size: int = 420,
) -> str:
    """Return an SVG string of a 6-axis radar chart.

    Each mode is drawn as one polygon in its own color.
    """
    import math

    cx = cy = size / 2
    plot_r = size * 0.36
    label_r = size * 0.44
    n = len(_RADAR_AXES)
    angle_step = 2 * math.pi / n

    svg_parts: list[str] = [
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'style="max-width:100%;font-family:system-ui,sans-serif;">',
    ]

    # Grid rings (20%, 40%, 60%, 80%, 100%)
    for ring_pct in (0.2, 0.4, 0.6, 0.8, 1.0):
        points = " ".join(
            f"{_polar(cx, cy, plot_r * ring_pct, i * angle_step)[0]:.1f},"
            f"{_polar(cx, cy, plot_r * ring_pct, i * angle_step)[1]:.1f}"
            for i in range(n)
        )
        svg_parts.append(
            f'<polygon points="{points}" fill="none" stroke="#e5e7eb" '
            f'stroke-width="1" opacity="0.8"/>'
        )

    # Axis lines + labels
    for i, (label_name, _, _) in enumerate(_RADAR_AXES):
        x, y = _polar(cx, cy, plot_r, i * angle_step)
        lx, ly = _polar(cx, cy, label_r, i * angle_step)
        svg_parts.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="#d1d5db" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'dy=".35em" font-size="12" fill="#374151">{label_name}</text>'
        )

    # One polygon per mode
    for mr in per_mode_results:
        color = _RADAR_COLORS.get(mr.mode, "#6b7280")
        metrics = mr.metrics
        points_list: list[tuple[float, float]] = []
        for i, (_, field_name, inverted) in enumerate(_RADAR_AXES):
            raw_val = float(getattr(metrics, field_name, 0))
            max_val = _RADAR_MAX.get(field_name, max(raw_val, 1.0))
            if inverted:
                # For declassification: higher completeness → closer to outer ring
                norm = min(max(raw_val / max_val, 0.0), 1.0)
            else:
                # For violation counters: lower count → closer to outer ring
                norm = 1.0 - min(max(raw_val / max_val, 0.0), 1.0)
            px, py = _polar(cx, cy, plot_r * norm, i * angle_step)
            points_list.append((px, py))
        points_str = " ".join(f"{pt[0]:.1f},{pt[1]:.1f}" for pt in points_list)
        svg_parts.append(
            f'<polygon points="{points_str}" fill="{color}" fill-opacity="0.2" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        # Data points
        for pt in points_list:
            svg_parts.append(
                f'<circle cx="{pt[0]:.1f}" cy="{pt[1]:.1f}" r="3" fill="{color}"/>'
            )

    # Legend
    legend_y = 20
    for i, mr in enumerate(per_mode_results):
        color = _RADAR_COLORS.get(mr.mode, "#6b7280")
        svg_parts.append(
            f'<rect x="{size - 120}" y="{legend_y + i * 20}" width="12" height="12" '
            f'fill="{color}" fill-opacity="0.4" stroke="{color}" stroke-width="1.5"/>'
        )
        svg_parts.append(
            f'<text x="{size - 100}" y="{legend_y + i * 20 + 10}" '
            f'font-size="12" fill="#374151">{mr.mode}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# ---------------------------------------------------------------------------
# HTMLRenderer
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HTMLRenderer:
    """Loads Jinja2 templates and renders KTSL reports to HTML strings."""

    def __init__(self, template_dir: Path | None = None) -> None:
        if not _JINJA2_AVAILABLE:
            raise ImportError(
                "jinja2 is required for HTML rendering. "
                "Install it with: pip install jinja2"
            )
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"
        self._template_dir = Path(template_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=False,  # offline reports; content is trusted
            keep_trailing_newline=True,
        )

    # ------------------------------------------------------------------
    def render_session(self, report: SessionReport) -> str:
        """Render a SessionReport to a complete HTML document."""
        try:
            template = self._env.get_template("session.html.j2")
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template 'session.html.j2' not found in {self._template_dir}"
            )
        return template.render(report=report, now=_now_iso())

    def render_publish(self, report: PublishReport) -> str:
        """Render a PublishReport to a complete HTML document (with radar SVG)."""
        try:
            template = self._env.get_template("publish.html.j2")
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template 'publish.html.j2' not found in {self._template_dir}"
            )
        radar_svg = _build_radar_svg(report.per_mode)

        # Build metric_rows: list of {label, cells [{value, pass}, ...], threshold}
        metric_rows = _build_publish_metric_rows(report)
        return template.render(
            report=report,
            radar_svg=radar_svg,
            metric_rows=metric_rows,
            now=_now_iso(),
        )

    def render_validate(self, report: ValidateReport) -> str:
        """Render a ValidateReport to a complete HTML document."""
        try:
            template = self._env.get_template("validate.html.j2")
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template 'validate.html.j2' not found in {self._template_dir}"
            )
        errors = [i for i in report.issues if i.level == "error"]
        warnings = [i for i in report.issues if i.level == "warning"]
        infos = [i for i in report.issues if i.level == "info"]
        exit_code = 2 if errors else (1 if warnings else 0)
        return template.render(
            report=report,
            error_count=len(errors),
            warning_count=len(warnings),
            info_count=len(infos),
            exit_code=exit_code,
            now=_now_iso(),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def render_to_file(content: str, path: Path) -> None:
        """Write an HTML string to disk."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_METRIC_LABELS = [
    ("Causal Violations", "causal_violation_count"),
    ("Unauthorized Actions", "unauthorized_action_count"),
    ("Public Payload Leaks", "public_payload_leak_count"),
    ("Spotlight Max Gap (min)", "spotlight_max_gap_minutes"),
    ("Declassification", "declassification_completeness"),
    ("Retcons", "retcon_count"),
    ("High-Coupling Drift (min)", "high_coupling_time_drift_minutes"),
]

_THRESHOLD_FIELD_MAP = {
    "causal_violation_count": "max_causal_violations",
    "unauthorized_action_count": "max_unauthorized_actions",
    "public_payload_leak_count": "max_public_payload_leaks",
    "spotlight_max_gap_minutes": "max_spotlight_gap_minutes",
    "declassification_completeness": "min_declassification_completeness",
    "retcon_count": "max_retcons",
    "high_coupling_time_drift_minutes": "max_high_coupling_drift_minutes",
}


def _build_publish_metric_rows(report: PublishReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, field_name in _METRIC_LABELS:
        cells: list[dict[str, Any]] = []
        threshold_strs: list[str] = []
        for mr in report.per_mode:
            val = getattr(mr.metrics, field_name)
            display = f"{val:.2f}" if isinstance(val, float) else str(val)
            cells.append({"value": display, "pass": mr.passed})
            thresh_obj = report.thresholds.get(mr.mode)
            if thresh_obj is not None:
                tfield = _THRESHOLD_FIELD_MAP.get(field_name)
                tval = getattr(thresh_obj, tfield, None) if tfield else None
                if tval is not None:
                    threshold_strs.append(f"{tval:.2f}" if isinstance(tval, float) else str(tval))
                else:
                    threshold_strs.append("—")
            else:
                threshold_strs.append("—")
        rows.append({
            "label": label,
            "cells": cells,
            "threshold": " / ".join(threshold_strs) if threshold_strs else "—",
        })
    return rows


__all__ = ["HTMLRenderer", "_build_radar_svg"]

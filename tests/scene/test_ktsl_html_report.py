"""Tests for KTSL HTMLRenderer (Phase 4)."""

from __future__ import annotations

from pathlib import Path

from scenario.report.html_renderer import HTMLRenderer, _build_radar_svg
from scenario.report.session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    MetricSummary,
    ModeResult,
    PublishReport,
    SessionConfig,
    SessionReport,
    ValidateIssue,
    ValidateReport,
    ViolationEvent,
)


def _sample_metrics() -> MetricSummary:
    return MetricSummary(
        causal_violation_count=0,
        unauthorized_action_count=1,
        public_payload_leak_count=0,
        spotlight_max_gap_minutes=25,
        declassification_completeness=0.97,
        retcon_count=0,
    )


def _sample_session_report() -> SessionReport:
    metrics = _sample_metrics()
    violations = [
        ViolationEvent(
            event_id="evt_003",
            event_index=3,
            actor="李",
            action_text="偷偷跟踪佐藤",
            scene_id="street",
            severity="warning",
            metric="public_payload_leak",
            message="Potential info leak",
        ),
        ViolationEvent(
            event_id="evt_007",
            event_index=7,
            actor="佐藤",
            action_text="跳过 barrier B3",
            scene_id="old_house",
            severity="error",
            metric="causal_violation",
            message="Barrier B3 not satisfied",
            overridden=True,
        ),
    ]
    knowledge_map = {
        "佐藤": [
            KnowledgeItemView(
                info_id="info_07",
                kind="know",
                sensitivity="low",
                content_summary="老宅档案室有一份旧搜查令",
                source_event_id="S001",
                source_scene_id="hospital_wing",
                acquired_at_minute=5,
            ),
        ],
        "李": [
            KnowledgeItemView(
                info_id="info_07",
                kind="obs",
                sensitivity="medium",
                content_summary="佐藤似乎在翻找档案柜",
                source_event_id="S003",
                source_scene_id="street",
                acquired_at_minute=15,
            ),
        ],
    }
    scene_timelines = {
        "hospital_wing": [
            EventSummary(
                event_id="evt_001",
                event_index=1,
                actor="佐藤",
                action_text="翻找档案柜",
                time_minute=5,
                output_info_ids=["info_07"],
            ),
        ],
        "street": [
            EventSummary(
                event_id="evt_003",
                event_index=3,
                actor="李",
                action_text="偷偷跟踪佐藤",
                time_minute=20,
            ),
        ],
    }
    barriers = [
        BarrierStateView(
            barrier_id="B1",
            status="satisfied",
            required_event_ids=["evt_001"],
            satisfied_event_ids=["evt_001"],
        ),
    ]
    couplings = [
        CouplingStateView(
            coupling_id="C1",
            source_scene_id="hospital_wing",
            target_scene_id="street",
            mode="linked",
            drift_minutes=5,
        ),
    ]
    return SessionReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="警察·医院·老宅",
        started_at="2026-07-04T19:00:00Z",
        ended_at="2026-07-04T20:00:00Z",
        session_config=SessionConfig(
            session_id="sess-20260704",
            fixture_id="police_station_hospital_old_house",
            kp_name="KP-佐藤",
        ),
        total_events=3,
        total_committed=2,
        total_blocked=0,
        total_overridden=1,
        metrics=metrics,
        violation_timeline=violations,
        final_knowledge_map=knowledge_map,
        scene_timelines=scene_timelines,
        barrier_final_states=barriers,
        coupling_final_states=couplings,
    )


def _sample_publish_report_pass() -> PublishReport:
    return PublishReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="警察·医院",
        evaluated_at="2026-07-04T20:00:00Z",
        criteria_version="1.0.0",
        overall_pass=True,
        per_mode=[
            ModeResult(mode="baseline", passed=True, metrics=MetricSummary()),
            ModeResult(mode="schedule_only", passed=True, metrics=MetricSummary()),
            ModeResult(mode="ktsl_full", passed=True, metrics=MetricSummary()),
        ],
    )


def _sample_publish_report_fail() -> PublishReport:
    return PublishReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="警察·医院",
        evaluated_at="2026-07-04T20:00:00Z",
        criteria_version="1.0.0",
        overall_pass=False,
        per_mode=[
            ModeResult(mode="baseline", passed=True, metrics=MetricSummary()),
            ModeResult(
                mode="ktsl_full",
                passed=False,
                metrics=MetricSummary(causal_violation_count=2, public_payload_leak_count=1),
                failures=["ktsl_full.causal_violation: 2 > 0"],
                warnings=[],
            ),
        ],
    )


def _sample_validate_report() -> ValidateReport:
    return ValidateReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="警察·医院",
        validated_at="2026-07-04T20:00:00Z",
        is_valid=True,
        issues=[
            ValidateIssue(level="info", code="structure_ok", message="All references valid"),
        ],
    )


def _sample_validate_report_with_issues() -> ValidateReport:
    return ValidateReport(
        fixture_id="broken",
        is_valid=False,
        issues=[
            ValidateIssue(level="error", code="circular_dependency", message="Cycle: A → B → A"),
            ValidateIssue(level="warning", code="orphan_info", message="info_99 not referenced"),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_session_produces_valid_html() -> None:
    """HTML output contains <html>, <body>, and key sections."""
    renderer = HTMLRenderer()
    report = _sample_session_report()
    html = renderer.render_session(report)
    assert "<html" in html
    assert "<body" in html
    assert "</html>" in html
    assert "metrics-dashboard" in html
    assert "violation-timeline" in html
    assert "knowledge-map" in html
    assert "scene-timelines" in html
    assert "barrier-states" in html
    assert "coupling-states" in html


def test_render_session_contains_metrics_cards() -> None:
    """HTML output contains 6 metric card CSS classes."""
    renderer = HTMLRenderer()
    report = _sample_session_report()
    html = renderer.render_session(report)
    expected_classes = [
        "card-causal",
        "card-unauth",
        "card-leak",
        "card-spot",
        "card-decl",
        "card-retcon",
    ]
    for cls in expected_classes:
        assert cls in html, f"Expected CSS class {cls!r} in HTML output"


def test_render_session_contains_knowledge_content_summary() -> None:
    """HTML output includes content_summary text (not just info_id)."""
    renderer = HTMLRenderer()
    report = _sample_session_report()
    html = renderer.render_session(report)
    assert "老宅档案室有一份旧搜查令" in html
    assert "佐藤似乎在翻找档案柜" in html


def test_render_session_no_external_cdn() -> None:
    """HTML output does not reference external CDNs."""
    renderer = HTMLRenderer()
    report = _sample_session_report()
    html = renderer.render_session(report)
    assert "cdn." not in html.lower()
    assert "googleapis" not in html.lower()
    assert "unpkg.com" not in html.lower()
    assert "jsdelivr" not in html.lower()


def test_render_publish_contains_verdict() -> None:
    """HTML publish report contains PASS or FAIL verdict text."""
    renderer = HTMLRenderer()
    report = _sample_publish_report_pass()
    html = renderer.render_publish(report)
    assert "PASS" in html
    assert "verdict" in html.lower()


def test_render_publish_contains_fail_verdict() -> None:
    """HTML publish report shows FAIL when overall_pass=False."""
    renderer = HTMLRenderer()
    report = _sample_publish_report_fail()
    html = renderer.render_publish(report)
    assert "FAIL" in html
    assert "ktsl_full.causal_violation" in html


def test_render_publish_contains_radar_svg() -> None:
    """HTML publish report contains <svg> element."""
    renderer = HTMLRenderer()
    report = _sample_publish_report_pass()
    html = renderer.render_publish(report)
    assert "<svg" in html
    assert "</svg>" in html


def test_render_publish_contains_mode_table() -> None:
    """HTML publish report contains mode comparison table."""
    renderer = HTMLRenderer()
    report = _sample_publish_report_pass()
    html = renderer.render_publish(report)
    assert "baseline" in html
    assert "schedule_only" in html
    assert "ktsl_full" in html


def test_render_publish_no_external_cdn() -> None:
    """HTML publish report does not reference external CDNs."""
    renderer = HTMLRenderer()
    report = _sample_publish_report_pass()
    html = renderer.render_publish(report)
    assert "cdn." not in html.lower()
    assert "googleapis" not in html.lower()


def test_render_validate_contains_issue_list() -> None:
    """HTML validate report contains issue list."""
    renderer = HTMLRenderer()
    report = _sample_validate_report_with_issues()
    html = renderer.render_validate(report)
    assert "circular_dependency" in html
    assert "orphan_info" in html
    assert "Cycle: A → B → A" in html


def test_render_validate_shows_pass() -> None:
    """HTML validate report shows PASS for valid fixture."""
    renderer = HTMLRenderer()
    report = _sample_validate_report()
    html = renderer.render_validate(report)
    assert "PASS" in html


def test_render_validate_shows_exit_code() -> None:
    """HTML validate report shows exit code."""
    renderer = HTMLRenderer()
    report = _sample_validate_report_with_issues()
    html = renderer.render_validate(report)
    assert "Exit code" in html


def test_render_validate_no_external_cdn() -> None:
    """HTML validate report does not reference external CDNs."""
    renderer = HTMLRenderer()
    report = _sample_validate_report()
    html = renderer.render_validate(report)
    assert "cdn." not in html.lower()
    assert "googleapis" not in html.lower()


def test_render_to_file_creates_file(tmp_path: Path) -> None:
    """render_to_file writes HTML to disk."""
    renderer = HTMLRenderer()
    report = _sample_session_report()
    html = renderer.render_session(report)
    out = tmp_path / "session-report.html"
    renderer.render_to_file(html, out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert "<html" in out.read_text(encoding="utf-8")


def test_radar_svg_generation() -> None:
    """_build_radar_svg produces a valid SVG string."""
    mr = ModeResult(
        mode="ktsl_full",
        passed=True,
        metrics=MetricSummary(),
    )
    svg = _build_radar_svg([mr])
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Causal" in svg
    assert "Retcon" in svg


def test_html_renderer_accepts_custom_template_dir(tmp_path: Path) -> None:
    """HTMLRenderer accepts a custom template_dir."""
    # Copy default templates to tmp
    import shutil

    default_dir = Path(__file__).resolve().parents[2] / "src" / "scenario" / "report" / "templates"
    target = tmp_path / "templates"
    shutil.copytree(default_dir, target)
    renderer = HTMLRenderer(template_dir=target)
    report = _sample_session_report()
    html = renderer.render_session(report)
    assert "<html" in html

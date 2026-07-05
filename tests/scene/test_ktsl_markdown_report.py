"""Tests for KTSL MarkdownRenderer (Phase 3)."""

from __future__ import annotations

from scenario.report.markdown_renderer import MarkdownRenderer, render_session, render_publish, render_validate
from scenario.report.session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    MetricSummary,
    ModeResult,
    ModeThresholds,
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
            EventSummary(
                event_id="evt_002",
                event_index=2,
                actor="医生",
                action_text="深夜进入档案室",
                time_minute=12,
                output_info_ids=["info_08"],
            ),
        ],
        "street": [
            EventSummary(
                event_id="evt_003",
                event_index=3,
                actor="李",
                action_text="偷偷跟踪佐藤",
                time_minute=20,
                status="committed",
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
        BarrierStateView(
            barrier_id="B3",
            status="waiting",
            required_info_ids=["info_07"],
            satisfied_info_ids=[],
        ),
    ]
    couplings = [
        CouplingStateView(
            coupling_id="C1",
            source_scene_id="hospital_wing",
            target_scene_id="street",
            mode="linked",
            drift_minutes=5,
            active=True,
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
                failures=[
                    "ktsl_full.causal_violation: 2 > 0",
                    "ktsl_full.public_payload_leak: 1 > 0",
                ],
                warnings=["ktsl_full.missing_threshold: spotlight_gap"],
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
            ValidateIssue(
                level="info",
                code="structure_ok",
                message="All SceneCard references valid",
            )
        ],
    )


def _sample_validate_report_with_issues() -> ValidateReport:
    return ValidateReport(
        fixture_id="broken",
        is_valid=False,
        issues=[
            ValidateIssue(
                level="error",
                code="circular_dependency",
                message="Cycle: A → B → A",
                resource_id="cdep_A",
            ),
            ValidateIssue(
                level="warning",
                code="orphan_info",
                message="info_99 not referenced",
                resource_id="info_99",
            ),
            ValidateIssue(
                level="info",
                code="stats",
                message="Fixture has 3 scenes",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests (acceptance criteria mapping)
# ---------------------------------------------------------------------------

def test_render_session_contains_all_metrics() -> None:
    """MD output includes all 6 core metric names."""
    report = _sample_session_report()
    md = render_session(report)
    expected_metric_labels = [
        "Causal Violations",
        "Unauthorized Actions",
        "Public Payload Leaks",
        "Spotlight Max Gap (min)",
        "Declassification",
        "Retcons",
    ]
    for label in expected_metric_labels:
        assert label in md, f"Expected metric {label!r} in markdown output"


def test_render_session_contains_knowledge_map() -> None:
    """MD output includes character rows in knowledge map."""
    report = _sample_session_report()
    md = render_session(report)
    assert "佐藤" in md
    assert "李" in md
    assert "info_07" in md


def test_render_session_contains_violations() -> None:
    """MD output includes violation event text."""
    report = _sample_session_report()
    md = render_session(report)
    assert "WARN" in md
    assert "ERROR" in md
    assert "OVERRIDDEN" in md
    # event_id shown in violation timeline
    assert "evt_003" in md
    assert "evt_007" in md


def test_render_session_contains_scene_timelines() -> None:
    """MD output includes scene timeline sections."""
    report = _sample_session_report()
    md = render_session(report)
    assert "hospital_wing" in md
    assert "street" in md
    assert "violation_timeline" not in md  # no snake_case leak


def test_render_session_contains_barrier_coupling() -> None:
    """MD output includes barrier state and coupling state sections."""
    report = _sample_session_report()
    md = render_session(report)
    assert "barrier_id" in md or "Barrier" in md
    assert "coupling_id" in md or "Coupling" in md
    assert "B3" in md
    assert "C1" in md


def test_render_publish_shows_pass() -> None:
    """MD publish report shows PASS verdict."""
    report = _sample_publish_report_pass()
    md = render_publish(report)
    assert "PASS" in md
    assert "Verdict: PASS" in md


def test_render_publish_shows_fail() -> None:
    """MD publish report shows FAIL verdict + failure list."""
    report = _sample_publish_report_fail()
    md = render_publish(report)
    assert "FAIL" in md
    assert "ktsl_full.causal_violation: 2 > 0" in md
    assert "ktsl_full.public_payload_leak: 1 > 0" in md


def test_render_publish_shows_warnings() -> None:
    """MD publish report shows warnings section."""
    report = _sample_publish_report_fail()
    md = render_publish(report)
    assert "Warnings" in md
    assert "missing_threshold" in md


def test_render_publish_mode_comparison() -> None:
    """MD publish report includes all mode columns."""
    report = _sample_publish_report_pass()
    md = render_publish(report)
    assert "baseline" in md
    assert "schedule_only" in md
    assert "ktsl_full" in md


def test_render_validate_shows_errors() -> None:
    """MD validate report renders errors."""
    report = _sample_validate_report_with_issues()
    md = render_validate(report)
    assert "ERROR" in md
    assert "circular_dependency" in md
    assert "Cycle: A → B → A" in md


def test_render_validate_shows_warnings() -> None:
    """MD validate report renders warnings."""
    report = _sample_validate_report_with_issues()
    md = render_validate(report)
    assert "WARN" in md
    assert "orphan_info" in md


def test_render_validate_shows_infos() -> None:
    """MD validate report renders info-level issues."""
    report = _sample_validate_report_with_issues()
    md = render_validate(report)
    assert "INFO" in md
    assert "Fixture has 3 scenes" in md


def test_render_validate_exit_code() -> None:
    """MD validate report shows exit code hint."""
    report = _sample_validate_report_with_issues()
    md = render_validate(report)
    assert "Exit code" in md


def test_render_validate_valid_report() -> None:
    """MD validate report for valid fixture has no ERROR."""
    report = _sample_validate_report()
    md = render_validate(report)
    assert "PASS" in md
    assert "ERROR" not in md


def test_markdown_renderer_class_api() -> None:
    """MarkdownRenderer class methods produce same output as module-level functions."""
    report = _sample_session_report()
    cls_out = MarkdownRenderer.render_session(report)
    fn_out = render_session(report)
    assert cls_out == fn_out


def test_publish_with_thresholds_shown() -> None:
    """Publish threshold data rendered in mode comparison table."""
    thresholds = {
        "ktsl_full": ModeThresholds(max_causal_violations=0, max_retcons=0),
    }
    mr = ModeResult(
        mode="ktsl_full",
        passed=True,
        metrics=MetricSummary(),
    )
    report = PublishReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="警察·医院",
        evaluated_at="2026-07-04T20:00:00Z",
        criteria_version="1.0.0",
        overall_pass=True,
        per_mode=[mr],
        thresholds=thresholds,
    )
    md = render_publish(report)
    assert "Threshold" in md

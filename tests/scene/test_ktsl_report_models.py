"""Tests for ktsl report data models (Phase 3 session_reports.py)."""

from __future__ import annotations

from scenario.report.session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    MetricSummary,
    ModeResult,
    ModeThresholds,
    PublishCriteria,
    PublishGateResult,
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


def _sample_knowledge_map() -> dict[str, list[KnowledgeItemView]]:
    return {
        "佐藤": [
            KnowledgeItemView(
                info_id="info_07",
                kind="know",
                sensitivity="low",
                content_summary="Details of an old police search warrant",
                source_event_id="S001",
                source_scene_id="hospital_wing",
                acquired_at_minute=5,
            )
        ],
        "李": [
            KnowledgeItemView(
                info_id="info_07",
                kind="obs",
                sensitivity="medium",
                content_summary="Sato appears to be looking for something",
                source_event_id="S003",
                source_scene_id="street",
                acquired_at_minute=15,
            )
        ],
    }


def test_session_report_model_constructs() -> None:
    """SessionReport can be constructed with required fields."""
    metrics = _sample_metrics()
    report = SessionReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="Police · Hospital · Old House",
        started_at="2026-07-04T19:00:00Z",
        ended_at="2026-07-04T20:00:00Z",
        session_config=SessionConfig(fixture_id="police_station_hospital_old_house"),
        total_events=5,
        total_committed=4,
        total_blocked=1,
        total_overridden=0,
        metrics=metrics,
    )
    assert report.fixture_id == "police_station_hospital_old_house"
    assert report.total_events == 5
    assert report.metrics.declassification_completeness == 0.97


def test_session_report_model_accepts_full_fields() -> None:
    """SessionReport accepts all optional rich fields."""
    metrics = _sample_metrics()
    violations = [
        ViolationEvent(
            event_id="evt_001",
            event_index=1,
            actor="佐藤",
            action_text="search records",
            scene_id="hospital_wing",
            severity="error",
            metric="causal_violation",
            message="Barrier B3 not satisfied",
            overridden=True,
        )
    ]
    knowledge_map = _sample_knowledge_map()
    scene_timelines = {
        "hospital_wing": [
            EventSummary(
                event_id="evt_001",
                event_index=1,
                actor="佐藤",
                action_text="search records",
                time_minute=5,
                output_info_ids=["info_07"],
            )
        ]
    }
    barriers = [BarrierStateView(barrier_id="B1", status="satisfied")]
    couplings = [CouplingStateView(
        coupling_id="C1",
        source_scene_id="hospital_wing",
        target_scene_id="street",
        mode="linked",
        drift_minutes=5,
    )]
    report = SessionReport(
        fixture_id="fixture_x",
        fixture_title="X",
        started_at="2026-07-04T19:00:00Z",
        ended_at="2026-07-04T20:00:00Z",
        session_config=SessionConfig(fixture_id="fixture_x"),
        total_events=1,
        total_committed=1,
        total_blocked=0,
        total_overridden=0,
        metrics=metrics,
        violation_timeline=violations,
        final_knowledge_map=knowledge_map,
        scene_timelines=scene_timelines,
        barrier_final_states=barriers,
        coupling_final_states=couplings,
    )
    assert len(report.violation_timeline) == 1
    assert "佐藤" in report.final_knowledge_map
    assert "hospital_wing" in report.scene_timelines
    assert report.barrier_final_states[0].barrier_id == "B1"
    assert report.coupling_final_states[0].drift_minutes == 5


def test_publish_report_model_constructs() -> None:
    """PublishReport can be constructed with required fields."""
    metrics = _sample_metrics()
    mr = ModeResult(
        mode="ktsl_full",
        passed=True,
        metrics=metrics,
        failures=[],
        warnings=[],
    )
    report = PublishReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="Police · Hospital",
        evaluated_at="2026-07-04T20:00:00Z",
        criteria_version="1.0.0",
        overall_pass=True,
        per_mode=[mr],
    )
    assert report.overall_pass is True
    assert report.per_mode[0].mode == "ktsl_full"
    assert report.per_mode[0].passed is True


def test_publish_report_with_thresholds() -> None:
    """PublishReport accepts thresholds mapping."""
    thresholds = {
        "baseline": ModeThresholds(max_causal_violations=5),
        "ktsl_full": ModeThresholds(max_causal_violations=0, max_retcons=0),
    }
    mr_base = ModeResult(
        mode="baseline",
        passed=True,
        metrics=_sample_metrics(),
        failures=[],
        warnings=[],
    )
    mr_full = ModeResult(
        mode="ktsl_full",
        passed=False,
        metrics=MetricSummary(causal_violation_count=2),
        failures=["ktsl_full.causal_violation: 2 > 0"],
        warnings=[],
    )
    report = PublishReport(
        fixture_id="f",
        fixture_title="T",
        evaluated_at="2026-07-04T20:00:00Z",
        criteria_version="1.0.0",
        overall_pass=False,
        per_mode=[mr_base, mr_full],
        thresholds=thresholds,
    )
    assert report.thresholds["ktsl_full"].max_causal_violations == 0
    assert not report.overall_pass


def test_validate_report_model_constructs() -> None:
    """ValidateReport can be constructed and identifies issues."""
    report = ValidateReport(
        fixture_id="police_station_hospital_old_house",
        fixture_title="Police · Hospital",
        validated_at="2026-07-04T20:00:00Z",
        is_valid=True,
        issues=[
            ValidateIssue(
                level="info",
                code="structure_ok",
                message="All references valid",
            )
        ],
    )
    assert report.is_valid is True
    assert len(report.issues) == 1


def test_validate_report_with_errors() -> None:
    """ValidateReport with errors has is_valid=False."""
    report = ValidateReport(
        fixture_id="broken_fixture",
        is_valid=False,
        issues=[
            ValidateIssue(
                level="error",
                code="circular_dependency",
                message="Dependency cycle detected: A → B → A",
                resource_id="cdep_A",
            ),
            ValidateIssue(
                level="warning",
                code="orphan_info",
                message="info_99 is not referenced by any event",
                resource_id="info_99",
            ),
        ],
    )
    errors = [i for i in report.issues if i.level == "error"]
    warnings = [i for i in report.issues if i.level == "warning"]
    assert len(errors) == 1
    assert len(warnings) == 1
    assert report.is_valid is False
    assert errors[0].code == "circular_dependency"


def test_knowledge_item_view_content_summary_field() -> None:
    """KnowledgeItemView has a required content_summary field."""
    item = KnowledgeItemView(
        info_id="info_01",
        kind="know",
        sensitivity="public",
        content_summary="Public visible info: library is open",
        source_event_id="S000",
        source_scene_id="library",
    )
    assert item.content_summary == "Public visible info: library is open"


def test_publish_criteria_and_gate_roundtrip() -> None:
    """PublishCriteria / PublishGateResult models can be constructed."""
    criteria = PublishCriteria(
        version="1.0.0",
        fixture_id="police_station_hospital_old_house",
        thresholds={
            "baseline": ModeThresholds(max_causal_violations=5),
            "ktsl_full": ModeThresholds(max_causal_violations=0, max_retcons=0),
        },
    )
    assert criteria.version == "1.0.0"
    assert criteria.thresholds["ktsl_full"].max_causal_violations == 0

    gate = PublishGateResult(
        overall_pass=True,
        per_mode=[
            ModeResult(
                mode="baseline",
                passed=True,
                metrics=_sample_metrics(),
            )
        ],
        evaluated_at="2026-07-04T20:00:00Z",
        fixture_id=criteria.fixture_id,
        criteria_version=criteria.version,
    )
    assert gate.overall_pass is True

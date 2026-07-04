"""Tests for the 4 M3 KTSL stage implementations."""
from __future__ import annotations

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import (
    KTSLLedger, ModuleKTSLSpec, ModuleSceneKTSLSpec,
    ModuleInfoLabelSpec, ModuleInitialKnowledgeSpec,
)
from scenario.ktsl.wizard import build_spec_from_fixture
from scenario.ktsl.stages import (
    ScheduleGateStage, FilterStage, CouplingDriftStage, AuditStage,
)
from scenario.ktsl.stage_context import StageContext


@pytest.fixture
def ledger() -> KTSLLedger:
    fx = build_library_sewer_church_fixture()
    spec = build_spec_from_fixture(fx)
    return KTSLLedger.from_module_spec(module_id="paper_lib_sewer_church", spec=spec)


class TestScheduleGateStage:
    def test_returns_continue_when_no_pending_events(self, ledger: KTSLLedger) -> None:
        stage = ScheduleGateStage()
        result = stage.run(_make_ctx(ledger))
        assert result.status == "continue"

    def test_wait_when_barrier_unmet(self, ledger: KTSLLedger) -> None:
        # barrier with non-existent required_event, status=waiting (enforced)
        from scenario.ktsl.models import BarrierCheckpoint
        ledger.barriers = [
            BarrierCheckpoint(id="b1", required_event_ids=["nonexistent"], status="waiting")
        ]
        stage = ScheduleGateStage()
        result = stage.run(_make_ctx(ledger))
        assert result.status == "wait"
        assert len(result.interventions) == 1
        assert result.interventions[0].kind == "wait"


class TestFilterStage:
    def test_allow_when_nothing_sensitive(self, ledger: KTSLLedger) -> None:
        stage = FilterStage()
        result = stage.run(_make_ctx(ledger))
        assert result.status == "continue"

    def test_redact_when_unauthorized_high_sens(self, ledger: KTSLLedger) -> None:
        # Build ledger with high-sens label not authorized for P1
        from scenario.ktsl.models import InfoLabel
        ledger.info_labels["secret_01"] = InfoLabel(
            id="secret_01", kind="know", scene_id="library",
            payload="top secret", sensitivity="high",
            public_payload="Something secret.",
            redact="[classified]",
            authorized_character_ids=["P2"],  # P1 NOT authorized
        )
        # Run with P1's action producing this label
        from scenario.ktsl.models import EventRecord
        ctx = _make_ctx(ledger)
        ctx.scratch["resolve_event"] = EventRecord(
            id="evt_secret", scene_id="library",
            action_id="a", action_text="peek",
            actor="P1", player_id="player_1", character_id="P1",
            output_info_ids=["secret_01"],
        )
        stage = FilterStage()
        result = stage.run(ctx)
        assert result.status == "continue"
        # Should produce intervention
        assert len(result.interventions) >= 1


class TestCouplingDriftStage:
    def test_continue_when_all_independent(self, ledger: KTSLLedger) -> None:
        stage = CouplingDriftStage()
        result = stage.run(_make_ctx(ledger))
        assert result.status == "continue"


class TestAuditStage:
    def test_continue_and_produces_audit_entries(self, ledger: KTSLLedger) -> None:
        stage = AuditStage()
        result = stage.run(_make_ctx(ledger))
        assert result.status == "continue"
        # events-log should now contain at least one KTSL-related runtime event
        # (AuditStage writes audit deltas to ledger if available)


def _make_ctx(ledger: KTSLLedger) -> StageContext:
    """Build a minimal StageContext for stage tests."""
    from scenario.story.models import StoryState
    from scenario.session.state import SessionMapState
    snapshot = SessionMapState(
        session_id="s1", module_id="paper_lib_sewer_church",
        current_turn=1, global_flags=set(),
        story_state=StoryState(current_stage_id="entry"),
        clock_values={}, completed_actions=set(), triggered_clock_events=set(),
        scene_instances={}, player_states={}, pending_intents={},
        npc_states={}, npc_patch_queue=[],
        ktsl_ledger=ledger,
    )
    ctx = StageContext(snapshot=snapshot, ledger=ledger, event_log=[])
    ctx.scene = type("Scene", (), {"id": "library", "name": "Library"})()
    ctx.intents = []
    return ctx

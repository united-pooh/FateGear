"""Tests for KTSLLedger integration with SessionMapState."""
from __future__ import annotations


from scenario.ktsl.models import KTSLLedger


def _make_minimal_session_kwargs() -> dict:
    """Build minimal SessionMapState kwargs using only required fields."""
    from scenario.story.models import StoryState

    return {
        "session_id": "s1",
        "module_id": "m1",
        "current_turn": 1,
        "global_flags": set(),
        "story_state": StoryState(current_stage_id="entry"),
        "clock_values": {},
        "completed_actions": set(),
        "triggered_clock_events": set(),
        "scene_instances": {},
        "player_states": {},
        "pending_intents": {},
        "npc_states": {},
        "npc_patch_queue": [],
    }


class TestSessionMapStateKTSLFields:
    def test_ktsl_ledger_field_defaults_none(self) -> None:
        kwargs = _make_minimal_session_kwargs()
        from scenario.session.state import SessionMapState

        session = SessionMapState(**kwargs)
        assert session.ktsl_ledger is None

    def test_ktsl_ledger_can_be_attached(self) -> None:
        from scenario.session.state import SessionMapState

        ledger = KTSLLedger.empty(module_id="m1")
        kwargs = _make_minimal_session_kwargs()
        session = SessionMapState(**kwargs, ktsl_ledger=ledger)
        assert session.ktsl_ledger is not None
        assert session.ktsl_ledger.module_id == "m1"

    def test_ledger_survives_model_copy(self) -> None:
        from scenario.session.state import SessionMapState

        ledger = KTSLLedger.empty(module_id="m1")
        kwargs = _make_minimal_session_kwargs()
        session = SessionMapState(**kwargs, ktsl_ledger=ledger)
        snap = session.model_copy(deep=True)
        assert snap.ktsl_ledger is not None
        assert snap.ktsl_ledger.module_id == "m1"

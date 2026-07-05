"""Tests for KTSL-specific RuntimeEvent types."""
from __future__ import annotations

from scenario.runtime.contracts import RuntimeEvent


class TestKTSLRuntimeEventTypes:
    def test_ktsl_intervention_event_accepted(self) -> None:
        event = RuntimeEvent(
            type="ktsl_intervention_issued",
            message="P1 action blocked: empty text",
            turn_no=1,
        )
        assert event.type == "ktsl_intervention_issued"

    def test_ktsl_override_event_accepted(self) -> None:
        event = RuntimeEvent(
            type="ktsl_override_applied",
            message="KP override on evt_001",
            turn_no=2,
        )
        assert event.type == "ktsl_override_applied"

    def test_ktsl_audit_event_accepted(self) -> None:
        event = RuntimeEvent(
            type="ktsl_audit_updated",
            message="Turn 2 audit metrics computed",
            turn_no=2,
        )
        assert event.type == "ktsl_audit_updated"

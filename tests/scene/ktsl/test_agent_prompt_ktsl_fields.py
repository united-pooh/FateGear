"""Tests for AgentPlanPrompt / CommitResult carrying KTSL fields."""
from __future__ import annotations

import pytest

from scenario.agent.models import (
    AgentPlanPrompt,
    CommitResult,
    ModuleLayer,
    SpatialLayer,
)


@pytest.fixture
def sample_ktsl_context() -> dict[str, object]:
    """A representative KTSL context object."""
    return {
        "coupling_summary": {
            "library": {"mode": "independent", "coupling_score": 0.0},
        },
        "barrier_debt": [],
        "wait_warnings": [],
        "pending_causal_edges": [],
    }


class TestAgentPlanPromptKTSLFields:
    def test_defaults_to_none_without_ktsl(self) -> None:
        prompt = AgentPlanPrompt(
            session_id="s1",
            turn_no=1,
            scene_id="sc1",
            module=ModuleLayer(module_id="m1", current_stage_id="st1"),
            spatial=SpatialLayer(scene_id="sc1"),
        )
        assert prompt.ktsl_context is None

    def test_accepts_ktsl_context(
        self, sample_ktsl_context: dict[str, object]
    ) -> None:
        prompt = AgentPlanPrompt(
            session_id="s1",
            turn_no=1,
            scene_id="sc1",
            module=ModuleLayer(module_id="m1", current_stage_id="st1"),
            spatial=SpatialLayer(scene_id="sc1"),
            ktsl_context=sample_ktsl_context,
        )
        assert prompt.ktsl_context == sample_ktsl_context


class TestCommitResultKTSLFields:
    def test_defaults_to_empty_list(self) -> None:
        commit = CommitResult(session_id="s1", turn_no=1, scene_id="sc1")
        assert commit.ktsl_filter_decisions == []

    def test_accepts_filter_decisions(self) -> None:
        decisions = [
            {
                "character_id": "P1",
                "info_id": "I01",
                "status": "redacted",
                "public_payload": "[withheld]",
            }
        ]
        commit = CommitResult(
            session_id="s1",
            turn_no=1,
            scene_id="sc1",
            ktsl_filter_decisions=decisions,
        )
        assert commit.ktsl_filter_decisions == decisions

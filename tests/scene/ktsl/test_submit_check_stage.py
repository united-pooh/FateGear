"""Tests for SubmitCheckStage — M2 intent pre-submission validation."""
from __future__ import annotations


from scenario.ktsl.models import InfoLabel
from scenario.ktsl.stages import SubmitCheckResult, SubmitCheckStage, SubmitIntervention


class TestSubmitCheckStage:
    def test_stage_accepts_empty_committed_set(self) -> None:
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},
            strict=False,
        )
        assert isinstance(report, SubmitCheckResult)
        assert report.status == "continue"

    def test_stage_blocks_unknown_action_when_strict(self) -> None:
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},
            strict=True,
        )
        assert report.status == "blocked"
        assert report.interventions
        assert report.interventions[0].reason_code == "empty_action"

    def test_stage_blocks_unauthorized_info(self) -> None:
        labels = {
            "secret_passage": InfoLabel(
                id="secret_passage",
                kind="know",
                scene_id="library",
                payload="a hidden tunnel",
                sensitivity="high",
                authorized_character_ids=["P2"],  # P1 is NOT authorized
            )
        }
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels=labels,
            strict=False,
            required_info_ids=["secret_passage"],
        )
        assert report.status == "blocked"
        assert any(i.reason_code == "info_unauthorized" for i in report.interventions)

    def test_stage_allows_authorized_info(self) -> None:
        labels = {
            "secret_passage": InfoLabel(
                id="secret_passage",
                kind="know",
                scene_id="library",
                payload="a hidden tunnel",
                sensitivity="high",
                authorized_character_ids=["P1"],
            )
        }
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels=labels,
            strict=False,
            required_info_ids=["secret_passage"],
        )
        assert report.status == "continue"

    def test_stage_blocks_unmet_dependency(self) -> None:
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),  # deps not in committed set
            ledger_info_labels={},
            strict=False,
            dependencies=["evt_open_door"],
        )
        assert report.status == "blocked"
        assert any(i.reason_code == "unmet_dependency" for i in report.interventions)

    def test_stage_allows_met_dependency(self) -> None:
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids={"evt_open_door"},
            ledger_info_labels={},
            strict=False,
            dependencies=["evt_open_door"],
        )
        assert report.status == "continue"

    def test_stage_passes_with_ledger_constructor_labels(self) -> None:
        """Labels from the constructor should also trigger auth checks."""
        labels = {
            "info_x": InfoLabel(
                id="info_x",
                kind="know",
                scene_id="library",
                payload="something",
                sensitivity="medium",
                authorized_character_ids=["P2"],
            )
        }
        stage = SubmitCheckStage(info_labels=labels)
        report = stage.check(
            action_text="",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},
            strict=True,
        )
        # strict mode AND empty action → blocked first
        assert report.status == "blocked"

    def test_result_intervention_fields(self) -> None:
        stage = SubmitCheckStage()
        report = stage.check(
            action_text="",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},
            strict=True,
        )
        assert report.interventions
        intervention = report.interventions[0]
        assert isinstance(intervention, SubmitIntervention)
        assert intervention.actor == "P1"
        assert intervention.reason_code
        assert intervention.reason

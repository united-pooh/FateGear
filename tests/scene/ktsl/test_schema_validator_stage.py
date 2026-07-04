"""Tests for SchemaValidatorStage."""
from __future__ import annotations

import pytest

from scenario.ktsl.models import (
    ModuleKTSLSpec,
    ModuleSceneKTSLSpec,
    ModuleInfoLabelSpec,
    ModuleInitialKnowledgeSpec,
)
from scenario.ktsl.stages import SchemaValidatorStage


class TestSchemaValidatorStage:
    def test_passes_when_spec_is_complete(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[
                ModuleSceneKTSLSpec(
                    scene_id="library",
                    participant_character_ids=["P1"],
                    participant_player_ids=["player_1"],
                )
            ],
            info_labels=[
                ModuleInfoLabelSpec(
                    info_id="I01",
                    payload="a clue",
                    sensitivity="high",
                    redaction="Sensitive info withheld.",
                    public_payload="Something was found.",
                )
            ],
            initial_knowledge=[
                ModuleInitialKnowledgeSpec(
                    character_id="P1",
                    known_info_ids=["I01"],
                )
            ],
        )
        stage = SchemaValidatorStage()
        report = stage.validate(spec)
        assert report.is_valid, f"Unexpected issues: {report.issues}"
        assert not report.issues

    def test_fails_when_high_sens_has_no_redaction(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[ModuleSceneKTSLSpec(scene_id="library", participant_character_ids=["P1"])],
            info_labels=[
                ModuleInfoLabelSpec(
                    info_id="I01",
                    payload="secret",
                    sensitivity="high",
                    redaction="",  # <-- missing
                    public_payload="Something found.",
                )
            ],
        )
        stage = SchemaValidatorStage()
        report = stage.validate(spec)
        assert not report.is_valid
        assert any("info_labels.I01.redaction" in i.field for i in report.issues)

    def test_fails_when_scene_has_no_participants(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[ModuleSceneKTSLSpec(scene_id="library", participant_character_ids=[])],
        )
        stage = SchemaValidatorStage()
        report = stage.validate(spec)
        assert not report.is_valid
        assert any("participant" in i.field for i in report.issues)

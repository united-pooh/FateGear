"""Interactive KTSL wizard: guide KP through 5 preparation steps.

Usage::

    python -m src.scenario.cli.ktsl_cli wizard <output_path>
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import (
    ModuleCouplingSpec,
    ModuleInitialKnowledgeSpec,
    ModuleInfoLabelSpec,
    ModuleKTSLSpec,
    ModuleSceneKTSLSpec,
)


def build_spec_from_fixture(fixture: Any) -> ModuleKTSLSpec:
    """Convert a KTSLFixture (offline oracle) into a ModuleKTSLSpec.

    Used by M1 gate tests and by `ktsl migrate` CLI. The converter
    derives scenes, info_labels, and initial_knowledge from fixture
    data; couplings are left empty for the KP to fill in later.
    """
    # --- scenes ---
    # Map each fixture SceneCard onto a ModuleSceneKTSLSpec.  The spec
    # uses the scene's location_id as the scene_id (bare names like
    # "library"), and carries over participant + participant_player ids.
    scenes = [
        ModuleSceneKTSLSpec(
            scene_id=scene.location_id,
            participant_character_ids=list(scene.participant_character_ids),
            participant_player_ids=list(scene.participant_player_ids),
            time_start_minute=scene.time_start_minute,
            time_end_minute=scene.time_end_minute,
            spotlight_start_minute=scene.spotlight_start_minute,
            spotlight_end_minute=scene.spotlight_end_minute,
            tags=list(scene.tags),
        )
        for scene in fixture.scenes
    ]

    # --- info_labels ---
    info_labels = []
    for info in fixture.info_labels:
        redaction = info.redaction or _default_redaction(info.payload)
        public_payload = info.public_payload or _default_public_payload(info.payload)
        info_labels.append(
            ModuleInfoLabelSpec(
                info_id=info.id,
                payload=info.payload,
                sensitivity=info.sensitivity,
                public_payload=public_payload,
                redaction=redaction,
                known_by_character_ids=list(info.known_by_character_ids),
                authorized_character_ids=list(info.authorized_character_ids),
            )
        )
    # Also add keeper truths as info_labels
    for truth in fixture.keeper_truths:
        existing = {il.info_id for il in info_labels}
        if truth.id not in existing:
            info_labels.append(
                ModuleInfoLabelSpec(
                    info_id=truth.id,
                    payload=truth.payload,
                    sensitivity="keeper",
                    public_payload="",
                    redaction=f"[KP-only] {truth.payload[:80]}",
                )
            )

    # --- couplings (left empty for the KP to fill in via wizard) ---
    couplings: list[ModuleCouplingSpec] = []

    # --- initial_knowledge ---
    initial_knowledge: list[ModuleInitialKnowledgeSpec] = []
    char_ids_from_events: set[str] = set()
    for event in fixture.events:
        if event.character_id:
            char_ids_from_events.add(event.character_id)

    knowledge_by_char: dict[str, ModuleInitialKnowledgeSpec] = {}
    for ak in fixture.initial_knowledge:
        spec = ModuleInitialKnowledgeSpec(
            character_id=ak.character_id,
            known_info_ids=list(ak.known_info_ids),
            observed_info_ids=list(ak.observed_info_ids),
            authorized_info_ids=list(ak.authorized_info_ids),
        )
        knowledge_by_char[ak.character_id] = spec
        initial_knowledge.append(spec)
    # Pad with empty specs for chars that only appear in events
    for char_id in sorted(char_ids_from_events):
        if char_id not in knowledge_by_char:
            initial_knowledge.append(
                ModuleInitialKnowledgeSpec(character_id=char_id)
            )

    return ModuleKTSLSpec(
        scenes=scenes,
        info_labels=info_labels,
        couplings=couplings,
        initial_knowledge=initial_knowledge,
    )


def _default_redaction(payload: str) -> str:
    return f"[Information restricted by KTSL. Payload length: {len(payload)} chars.]"


def _default_public_payload(payload: str) -> str:
    return payload[:120] + ("..." if len(payload) > 120 else "")


class WizardSession:
    """Interactive 5-step wizard for generating KTSL ledger."""

    def __init__(self, output_path: Path, module_id: str = "default") -> None:
        self.output_path = Path(output_path)
        self.module_id = module_id
        self.spec = ModuleKTSLSpec()

    def run_interactive(self) -> Path:
        """Run the interactive terminal session; return path to written ledger JSON."""
        self._step_scenes()
        self._step_info_labels()
        self._step_couplings()
        self._step_initial_knowledge()
        self._step_validate()
        return self._step_write_ledger()

    def _step_scenes(self) -> None:
        """Prompt user for scene definitions. (Stub: accepts pre-built spec via .spec)"""

    def _step_info_labels(self) -> None:
        """Prompt user for info label definitions. (Stub.)"""

    def _step_couplings(self) -> None:
        """Prompt user for scene coupling definitions. (Stub.)"""

    def _step_initial_knowledge(self) -> None:
        """Prompt user for initial character knowledge. (Stub.)"""

    def _step_validate(self) -> None:
        """Run SchemaValidatorStage; raise if validation fails."""
        from .stages import SchemaValidatorStage

        report = SchemaValidatorStage().validate(self.spec)
        if not report.is_valid:
            raise ValueError(
                "Schema validation failed:\n"
                + "\n".join(f"  - {i.field}: {i.message}" for i in report.issues)
            )

    def _step_write_ledger(self) -> Path:
        """Convert spec to KTSLLedger and write JSON to output_path."""
        from .models import KTSLLedger

        ledger = KTSLLedger.from_module_spec(
            module_id=self.module_id, spec=self.spec
        )
        self.output_path.write_text(ledger.model_dump_json(indent=2))
        return self.output_path

"""Deterministic replay helpers for narration records."""

from __future__ import annotations

from .contracts import (
    KeeperNarrationDraft,
    KeeperNarrationRecord,
    ModelMetadata,
    NarrationInputPacket,
    PromptBuildResult,
    VectorMemory,
)
from .prompt import NarrationPromptBuilder
from .records import build_narration_record
from .validator import NarrationValidator


def replay_narration_record(
    *,
    packet: NarrationInputPacket,
    draft: KeeperNarrationDraft,
    memories: list[VectorMemory] | None = None,
    model_metadata: ModelMetadata | None = None,
    prompt: PromptBuildResult | None = None,
) -> KeeperNarrationRecord:
    prompt_result = prompt or NarrationPromptBuilder().build(
        packet,
        memories=memories or [],
    )
    validation = NarrationValidator().validate(draft, packet, memories or [])
    return build_narration_record(
        packet=packet,
        validation=validation,
        prompt=prompt_result,
        model_metadata=model_metadata,
    )

"""Render-stage Keeper narration package."""

from .agent import CallableKeeperRenderAgent, KeeperRenderAgent, StaticKeeperRenderAgent
from .contracts import (
    CheckResultFact,
    KeeperNarrationDraft,
    KeeperNarrationRecord,
    ModelMetadata,
    NarrationEventRef,
    NarrationInputPacket,
    NarrationPatchProposal,
    NarrationValidationResult,
    NarrativeState,
    NpcLine,
    PatchApplicationResult,
    PromptBuildResult,
    PromptLayerSummary,
    RejectedPatchAudit,
    RuleFact,
    StateDiff,
    VectorMemory,
    VectorMemoryMetadata,
)
from .events import build_event_refs, event_ref_map, synthesize_event_id
from .graph_memory import SQLiteNarrationGraphMemory
from .input import build_narration_input_packet
from .memory import (
    InMemoryVectorContextStore,
    PersistentNarrationMemoryStore,
    VectorContextStore,
)
from .patches import validate_and_apply_patches, validate_patch
from .pipeline import NarrationGraphStore, NarrationPipeline
from .prompt import NarrationPromptBuilder
from .records import InMemoryNarrationRepository, build_narration_record
from .replay import replay_narration_record
from .validator import NarrationValidator

__all__ = [
    "CallableKeeperRenderAgent",
    "CheckResultFact",
    "InMemoryNarrationRepository",
    "InMemoryVectorContextStore",
    "KeeperNarrationDraft",
    "KeeperNarrationRecord",
    "KeeperRenderAgent",
    "ModelMetadata",
    "NarrationEventRef",
    "NarrationGraphStore",
    "NarrationInputPacket",
    "NarrationPatchProposal",
    "NarrationPipeline",
    "NarrationPromptBuilder",
    "NarrationValidationResult",
    "NarrationValidator",
    "NarrativeState",
    "NpcLine",
    "PatchApplicationResult",
    "PersistentNarrationMemoryStore",
    "PromptBuildResult",
    "PromptLayerSummary",
    "RejectedPatchAudit",
    "RuleFact",
    "StateDiff",
    "SQLiteNarrationGraphMemory",
    "StaticKeeperRenderAgent",
    "VectorContextStore",
    "VectorMemory",
    "VectorMemoryMetadata",
    "build_event_refs",
    "build_narration_input_packet",
    "build_narration_record",
    "event_ref_map",
    "replay_narration_record",
    "synthesize_event_id",
    "validate_and_apply_patches",
    "validate_patch",
]

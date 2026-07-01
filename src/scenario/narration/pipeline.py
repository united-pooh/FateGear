"""Post-resolution Keeper narration orchestration."""

from __future__ import annotations

from typing import Protocol

from scenario.module.models import ModuleDefinition
from scenario.runtime.contracts import TurnResolution
from scenario.session.state import SessionMapState

from .agent import KeeperRenderAgent
from .contracts import (
    KeeperNarrationRecord,
    ModelMetadata,
    NarrationValidationResult,
    PromptBuildResult,
    VectorMemory,
)
from .input import build_narration_input_packet
from .memory import InMemoryVectorContextStore, VectorContextStore
from .prompt import NarrationPromptBuilder
from .records import InMemoryNarrationRepository, build_narration_record
from .validator import NarrationValidator


class NarrationGraphStore(Protocol):
    """Accepted-record graph sink used by NarrationPipeline."""

    def ingest_record(self, record: KeeperNarrationRecord) -> object:
        """Persist graph facts derived from an accepted narration record."""


class NarrationPipeline:
    """Render narration after SceneRuntime has committed a turn."""

    def __init__(
        self,
        *,
        agent: KeeperRenderAgent,
        memory_store: VectorContextStore | None = None,
        repository: InMemoryNarrationRepository | None = None,
        prompt_builder: NarrationPromptBuilder | None = None,
        validator: NarrationValidator | None = None,
        model_metadata: ModelMetadata | None = None,
        graph_store: NarrationGraphStore | None = None,
    ) -> None:
        self.agent = agent
        self.memory_store = memory_store or InMemoryVectorContextStore()
        self.repository = repository or InMemoryNarrationRepository()
        self.prompt_builder = prompt_builder or NarrationPromptBuilder()
        self.validator = validator or NarrationValidator()
        self.model_metadata = model_metadata or ModelMetadata()
        self.graph_store = graph_store

    def render_after_turn(
        self,
        *,
        resolution: TurnResolution,
        session_snapshot: SessionMapState,
        module: ModuleDefinition,
        forbidden_facts: list[str] | None = None,
        max_prompt_chars: int | None = None,
    ) -> KeeperNarrationRecord:
        state = self.repository.get_state(resolution.session_id)
        packet = build_narration_input_packet(
            resolution=resolution,
            session=session_snapshot,
            module=module,
            narrative_state=state,
            forbidden_facts=forbidden_facts or [],
            recent_record_summary=self.repository.recent_summary(resolution.session_id),
        )
        memories = self.memory_store.retrieve(packet)
        packet.retrieved_memory_ids = [memory.memory_id for memory in memories]
        prompt = self.prompt_builder.build(
            packet,
            memories=memories,
            max_chars=max_prompt_chars,
        )
        try:
            draft: object = self.agent.render(prompt, packet, memories)
        except Exception as exc:  # pragma: no cover - exercised through validation result
            draft = {"schema_error": str(exc)}
        validation = self.validator.validate(draft, packet, memories)
        self.repository.save_state(resolution.session_id, validation.updated_state)
        record = build_narration_record(
            packet=packet,
            validation=validation,
            prompt=prompt,
            model_metadata=self.model_metadata,
        )
        self.repository.append_record(record)
        self.memory_store.write_from_record(record)
        if self.graph_store is not None:
            self.graph_store.ingest_record(record)
        return record


class NarrationRenderTrace:
    """Debug container for tests that need intermediate render-stage data."""

    def __init__(
        self,
        *,
        memories: list[VectorMemory],
        prompt: PromptBuildResult,
        validation: NarrationValidationResult,
        record: KeeperNarrationRecord,
    ) -> None:
        self.memories = memories
        self.prompt = prompt
        self.validation = validation
        self.record = record

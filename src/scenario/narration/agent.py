"""Keeper render agent boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from .contracts import (
    KeeperNarrationDraft,
    NarrationInputPacket,
    PromptBuildResult,
    VectorMemory,
)


class KeeperRenderAgent(Protocol):
    """Render-only agent: returns a draft and owns no persistence or state writes."""

    def render(
        self,
        prompt: PromptBuildResult,
        packet: NarrationInputPacket,
        memories: list[VectorMemory],
    ) -> KeeperNarrationDraft:
        """Return structured public narration for validation."""


class CallableKeeperRenderAgent:
    """Test-friendly adapter around a callable or static draft payload."""

    def __init__(
        self,
        renderer: Callable[
            [PromptBuildResult, NarrationInputPacket, list[VectorMemory]],
            KeeperNarrationDraft | Mapping[str, object],
        ],
    ) -> None:
        self._renderer = renderer

    def render(
        self,
        prompt: PromptBuildResult,
        packet: NarrationInputPacket,
        memories: list[VectorMemory],
    ) -> KeeperNarrationDraft:
        draft = self._renderer(prompt, packet, memories)
        if isinstance(draft, KeeperNarrationDraft):
            return draft
        return KeeperNarrationDraft.model_validate(draft)


class StaticKeeperRenderAgent:
    """Deterministic render agent for tests and examples."""

    def __init__(self, draft: KeeperNarrationDraft | Mapping[str, object]) -> None:
        self._draft = draft

    def render(
        self,
        prompt: PromptBuildResult,
        packet: NarrationInputPacket,
        memories: list[VectorMemory],
    ) -> KeeperNarrationDraft:
        if isinstance(self._draft, KeeperNarrationDraft):
            return self._draft
        return KeeperNarrationDraft.model_validate(self._draft)

"""Deterministic layered prompt builder for Keeper narration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .contracts import (
    NarrationInputPacket,
    PromptBuildResult,
    PromptLayerSummary,
    VectorMemory,
)


@dataclass(frozen=True)
class _Layer:
    name: str
    text: str
    required: bool


class NarrationPromptBuilder:
    """Compile committed facts, auxiliary context, and output schema."""

    def build(
        self,
        packet: NarrationInputPacket,
        *,
        memories: list[VectorMemory] | None = None,
        max_chars: int | None = None,
    ) -> PromptBuildResult:
        layers = self._layers(packet, memories or [])
        selected: list[_Layer] = []
        omitted: list[str] = []
        required_layers = [layer for layer in layers if layer.required]
        optional_layers = [layer for layer in layers if not layer.required]

        selected.extend(required_layers)
        if max_chars is None:
            selected.extend(optional_layers)
        else:
            used = _combined_length(selected)
            for layer in optional_layers:
                if used + len(layer.text) + 2 <= max_chars:
                    selected.append(layer)
                    used += len(layer.text) + 2
                else:
                    omitted.append(layer.name)

        prompt = "\n\n".join(layer.text for layer in selected)
        summaries = [
            PromptLayerSummary(
                name=layer.name,
                required=layer.required,
                char_count=len(layer.text),
                omitted=layer.name in omitted,
            )
            for layer in layers
        ]
        return PromptBuildResult(
            prompt=prompt,
            layers=summaries,
            omitted_layers=omitted,
            max_chars=max_chars,
        )

    def _layers(
        self,
        packet: NarrationInputPacket,
        memories: list[VectorMemory],
    ) -> list[_Layer]:
        return [
            _Layer(
                "permanent_rules",
                "\n".join(
                    [
                        "Permanent rules:",
                        "- Render only after committed runtime resolution.",
                        "- Committed RuntimeEvent and TurnResolution facts are authoritative.",
                        "- Vector memory and NarrativeState are auxiliary; never override facts.",
                        "- Output public narration only.",
                    ]
                ),
                True,
            ),
            _Layer(
                "authoritative_facts",
                "Authoritative facts:\n" + _json(
                    {
                        "session_id": packet.session_id,
                        "turn_no": packet.turn_no,
                        "module_id": packet.module_id,
                        "story": packet.story_snapshot.model_dump(mode="json"),
                        "players": [
                            item.model_dump(mode="json")
                            for item in packet.player_scene_snapshots
                        ],
                        "scenes": [
                            item.model_dump(mode="json")
                            for item in packet.scene_snapshots
                        ],
                        "rule_facts": [
                            item.model_dump(mode="json") for item in packet.rule_facts
                        ],
                    }
                ),
                True,
            ),
            _Layer(
                "current_event_ids",
                "Current event ids:\n" + _json(
                    [
                        {
                            "event_id": ref.event_id,
                            "type": ref.event_type,
                            "log_line": ref.log_line,
                        }
                        for ref in packet.event_refs
                    ]
                ),
                True,
            ),
            _Layer(
                "check_results_state_diffs_forbidden",
                "Check results, state diffs, and forbidden facts:\n" + _json(
                    {
                        "check_results": [
                            item.model_dump(mode="json")
                            for item in packet.check_results
                        ],
                        "state_diffs": [
                            item.model_dump(mode="json") for item in packet.state_diffs
                        ],
                        "forbidden_facts": packet.forbidden_facts,
                    }
                ),
                True,
            ),
            _Layer(
                "output_schema",
                "Output schema: KeeperNarrationDraft(public_text, npc_lines, "
                "keeper_notes, patch_proposals, source_event_ids, cited_memory_ids, "
                "style_notes). Patch targets must be public NarrativeState paths.",
                True,
            ),
            _Layer(
                "static_module_context",
                "Static module context:\n" + _json(
                    [
                        scene.model_dump(mode="json")
                        for scene in packet.static_scene_context
                    ]
                ),
                False,
            ),
            _Layer(
                "auxiliary_vector_memory",
                "Auxiliary vector memory, non-authoritative:\n" + _json(
                    [
                        {
                            "memory_id": memory.memory_id,
                            "kind": memory.metadata.kind,
                            "summary_text": memory.summary_text,
                        }
                        for memory in memories
                    ]
                ),
                False,
            ),
            _Layer(
                "narrative_state",
                "NarrativeState continuity, non-authoritative:\n"
                + _json(packet.narrative_state.model_dump(mode="json")),
                False,
            ),
        ]


def _combined_length(layers: list[_Layer]) -> int:
    if not layers:
        return 0
    return sum(len(layer.text) for layer in layers) + 2 * (len(layers) - 1)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)

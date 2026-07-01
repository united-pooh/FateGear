"""Safe template fallback for invalid or unsafe narration drafts."""

from __future__ import annotations

from .contracts import KeeperNarrationDraft, NarrationInputPacket


def build_safe_fallback_draft(
    packet: NarrationInputPacket,
    *,
    reasons: list[str] | None = None,
) -> KeeperNarrationDraft:
    lines = [event_ref.log_line for event_ref in packet.event_refs if event_ref.log_line]
    if not lines:
        lines = [
            f"第 {packet.turn_no} 回合已经结算，当前阶段为 "
            f"{packet.story_snapshot.current_stage_id}。"
        ]
    public_text = _redact_forbidden(" ".join(lines), packet.forbidden_facts)
    return KeeperNarrationDraft(
        public_text=public_text,
        npc_lines=[],
        keeper_notes=[f"fallback: {reason}" for reason in reasons or []],
        patch_proposals=[],
        source_event_ids=[event_ref.event_id for event_ref in packet.event_refs],
        cited_memory_ids=[],
        style_notes=["safe_template_fallback"],
    )


def _redact_forbidden(text: str, forbidden_facts: list[str]) -> str:
    redacted = text
    for fact in forbidden_facts:
        if fact:
            redacted = redacted.replace(fact, "[redacted]")
    return redacted

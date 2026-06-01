"""Validate Keeper narration drafts before persistence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .contracts import (
    KeeperNarrationDraft,
    NarrationInputPacket,
    NarrationValidationResult,
    VectorMemory,
)
from .fallback import build_safe_fallback_draft
from .memory import memory_conflicts_with_packet
from .patches import validate_and_apply_patches


class NarrationValidator:
    """Schema, citation, fact, memory, and patch validation."""

    def validate(
        self,
        draft: KeeperNarrationDraft | Mapping[str, Any] | object,
        packet: NarrationInputPacket,
        memories: list[VectorMemory] | None = None,
    ) -> NarrationValidationResult:
        parsed, schema_error = _parse_draft(draft)
        if schema_error is not None or parsed is None:
            return self._fallback(packet, [schema_error or "schema validation failed"])

        memories = memories or []
        fallback_reasons: list[str] = []
        warnings: list[str] = []
        known_event_ids = packet.event_ids
        known_memory_ids = {memory.memory_id for memory in memories}

        invalid_events = [
            event_id
            for event_id in parsed.source_event_ids
            if event_id not in known_event_ids
        ]
        if not parsed.source_event_ids:
            fallback_reasons.append("source_event_ids must reference current turn events")
        if invalid_events:
            fallback_reasons.append(f"invalid source_event_ids: {invalid_events}")

        invalid_memories = [
            memory_id
            for memory_id in parsed.cited_memory_ids
            if memory_id not in known_memory_ids
        ]
        if invalid_memories:
            fallback_reasons.append(f"invalid cited_memory_ids: {invalid_memories}")

        leaked = _forbidden_leaks(parsed, packet.forbidden_facts)
        if leaked:
            fallback_reasons.append(f"forbidden fact leakage: {leaked}")

        fact_conflicts = _fact_conflicts(parsed, packet)
        if fact_conflicts:
            fallback_reasons.extend(fact_conflicts)

        if _uses_vector_as_authority(parsed):
            fallback_reasons.append("vector memory used as authoritative fact")

        conflicting_memory_ids = [
            memory.memory_id
            for memory in memories
            if memory.memory_id in parsed.cited_memory_ids
            and memory_conflicts_with_packet(memory, packet)
        ]
        if conflicting_memory_ids:
            fallback_reasons.append(
                f"cited vector memory conflicts with committed facts: {conflicting_memory_ids}"
            )

        if fallback_reasons:
            return self._fallback(packet, fallback_reasons)

        patch_result = validate_and_apply_patches(
            packet.narrative_state,
            parsed.patch_proposals,
            packet.event_refs,
        )
        warnings.extend(rejection.reason for rejection in patch_result.rejected_patches)
        return NarrationValidationResult(
            final_draft=parsed,
            accepted_patches=patch_result.accepted_patches,
            rejected_patches=patch_result.rejected_patches,
            updated_state=patch_result.state,
            fallback_used=False,
            fallback_reasons=[],
            warnings=warnings,
        )

    def _fallback(
        self,
        packet: NarrationInputPacket,
        reasons: list[str],
    ) -> NarrationValidationResult:
        fallback = build_safe_fallback_draft(packet, reasons=reasons)
        return NarrationValidationResult(
            final_draft=fallback,
            accepted_patches=[],
            rejected_patches=[],
            updated_state=packet.narrative_state.model_copy(deep=True),
            fallback_used=True,
            fallback_reasons=reasons,
            warnings=reasons,
        )


def _parse_draft(
    draft: KeeperNarrationDraft | Mapping[str, Any] | object,
) -> tuple[KeeperNarrationDraft | None, str | None]:
    if isinstance(draft, KeeperNarrationDraft):
        return draft, None
    try:
        return KeeperNarrationDraft.model_validate(draft), None
    except ValidationError as exc:
        return None, str(exc)


def _forbidden_leaks(
    draft: KeeperNarrationDraft,
    forbidden_facts: list[str],
) -> list[str]:
    text = _draft_text(draft)
    return [fact for fact in forbidden_facts if fact and fact in text]


def _fact_conflicts(
    draft: KeeperNarrationDraft,
    packet: NarrationInputPacket,
) -> list[str]:
    text = _normalize(_draft_text(draft))
    conflicts: list[str] = []
    for check in packet.check_results:
        names = [_normalize(check.action_id), _normalize(check.action_name)]
        if not any(name and name in text for name in names):
            continue
        if check.success and _contains_failure_claim(text):
            conflicts.append(f"draft contradicts successful check {check.action_id}")
        if not check.success and _contains_success_claim(text):
            conflicts.append(f"draft contradicts failed check {check.action_id}")
    for event_ref in packet.event_refs:
        event = event_ref.runtime_event
        if event.success is not False:
            continue
        target_names = [
            _normalize(event.action_id),
            _normalize(event.action_name),
            _normalize(event.to_scene_name),
            _normalize(event.to_scene_id),
        ]
        if any(name and name in text for name in target_names) and _contains_success_claim(text):
            conflicts.append(f"draft contradicts failed event {event_ref.event_id}")
    conflicts.extend(_state_diff_conflicts(text, packet))
    conflicts.extend(_rule_fact_conflicts(text, packet))
    return list(dict.fromkeys(conflicts))


def _uses_vector_as_authority(draft: KeeperNarrationDraft) -> bool:
    text = _normalize(_draft_text(draft))
    return any(
        phrase in text
        for phrase in (
            "vector memory proves",
            "memory proves",
            "记忆证明",
            "向量记忆证明",
            "根据记忆可以确定",
        )
    )


def _draft_text(draft: KeeperNarrationDraft) -> str:
    parts = [draft.public_text, *draft.keeper_notes, *draft.style_notes]
    parts.extend(line.text for line in draft.npc_lines)
    return "\n".join(parts)


def _contains_success_claim(text: str) -> bool:
    return any(token in text for token in ("success", "succeeds", "成功", "顺利", "完成"))


def _contains_failure_claim(text: str) -> bool:
    return any(token in text for token in ("failed", "failure", "失败", "未能", "没有"))


def _normalize(value: str) -> str:
    return value.casefold().strip()


def _state_diff_conflicts(text: str, packet: NarrationInputPacket) -> list[str]:
    conflicts: list[str] = []
    for diff in packet.state_diffs:
        if diff.kind == "movement" and _movement_conflict(text, diff.old_value, diff.new_value):
            conflicts.append(f"draft contradicts committed movement {diff.path}")
        elif diff.kind == "flag_added" and _negative_claim_about(text, diff.path):
            conflicts.append(f"draft contradicts added flag {diff.path}")
        elif diff.kind == "flag_removed" and _positive_claim_about(text, diff.path):
            conflicts.append(f"draft contradicts removed flag {diff.path}")
        elif diff.kind == "clock_delta" and _clock_conflict(text, diff.path):
            conflicts.append(f"draft contradicts clock change {diff.path}")
        elif diff.kind == "story_transition" and _story_transition_conflict(
            text,
            diff.old_value,
            diff.new_value,
        ):
            conflicts.append(f"draft contradicts story transition {diff.path}")
        elif diff.kind == "ending" and _ending_conflict(text, diff.new_value):
            conflicts.append(f"draft contradicts ending {diff.path}")
    return conflicts


def _rule_fact_conflicts(text: str, packet: NarrationInputPacket) -> list[str]:
    conflicts: list[str] = []
    for fact in packet.rule_facts:
        if fact.kind != "completed_actions":
            continue
        for action_id in fact.data.get("completed_actions", []):
            if _token_present(text, action_id) and _contains_failure_claim(text):
                conflicts.append(f"draft contradicts completed action {action_id}")
    return conflicts


def _movement_conflict(text: str, old_value: object, new_value: object) -> bool:
    old_scene = _normalize(str(old_value or ""))
    new_scene = _normalize(str(new_value or ""))
    if new_scene and _token_present(text, new_scene) and _contains_any(
        text,
        (
            "did not enter",
            "didn't enter",
            "failed to move",
            "failed to enter",
            "无法进入",
            "没有进入",
            "未进入",
            "未能进入",
        ),
    ):
        return True
    return bool(
        old_scene
        and _token_present(text, old_scene)
        and _contains_any(text, ("still in", "remains in", "stayed in", "仍在", "还在", "留在"))
    )


def _story_transition_conflict(text: str, old_value: object, new_value: object) -> bool:
    old_stage = _normalize(str(old_value or ""))
    new_stage = _normalize(str(new_value or ""))
    if new_stage and _token_present(text, new_stage) and _contains_any(
        text,
        ("did not enter", "failed to transition", "没有进入", "未进入", "没有转入", "未转入"),
    ):
        return True
    return bool(
        old_stage
        and _token_present(text, old_stage)
        and _contains_any(
            text,
            ("still in", "remains in", "unchanged", "仍在", "还在", "没有变化", "未改变"),
        )
    )


def _clock_conflict(text: str, path: str) -> bool:
    clock_id = _normalize(path.rsplit(".", maxsplit=1)[-1])
    return bool(
        _token_present(text, clock_id)
        and _contains_any(
            text,
            (
                "unchanged",
                "did not advance",
                "not advance",
                "decreased",
                "没有推进",
                "未推进",
                "没有变化",
                "不变",
                "倒退",
            ),
        )
    )


def _ending_conflict(text: str, ending_id: object) -> bool:
    ending = _normalize(str(ending_id or ""))
    if ending and _token_present(text, ending) and _contains_any(
        text,
        ("no ending", "not ending", "did not end", "没有结局", "尚未结束", "未结束"),
    ):
        return True
    return "resolved_ending" in text and _contains_any(
        text,
        ("none", "null", "没有", "未", "尚未"),
    )


def _negative_claim_about(text: str, token: str) -> bool:
    return _token_present(text, token) and _contains_any(
        text,
        ("not set", "not present", "absent", "unset", "false", "没有", "未设置", "不存在", "未成立"),
    )


def _positive_claim_about(text: str, token: str) -> bool:
    return _token_present(text, token) and _contains_any(
        text,
        ("still set", "still present", "present", "set", "true", "仍然", "存在", "成立"),
    )


def _token_present(text: str, token: str) -> bool:
    token = _normalize(token)
    return bool(token and token in text)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(_normalize(token) in text for token in tokens)

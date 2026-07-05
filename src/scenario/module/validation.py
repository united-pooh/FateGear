"""YAML 模组语义校验。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from cards.domain.skills import SkillTemplate

from .models import ModuleDefinition
from .types import ModuleCondition, ModuleEffect
from ..story.models import StoryTransition


class _HasId(Protocol):
    id: str


class ModuleValidationError(ValueError):
    """模组结构或语义校验失败。"""


def validate_module_definition(
    *,
    definition: ModuleDefinition,
    source: Path,
    skill_templates: Mapping[str, SkillTemplate] | None = None,
) -> None:
    scene_ids = _ensure_unique_ids(
        definition.scenes,
        source=source,
        object_name="scene",
    )
    action_ids = _ensure_unique_ids(
        definition.actions,
        source=source,
        object_name="action",
    )
    clock_ids = _ensure_unique_ids(
        definition.clocks,
        source=source,
        object_name="clock",
    )
    story_stage_ids = _ensure_unique_ids(
        definition.story_stages,
        source=source,
        object_name="story_stage",
    )
    _ensure_unique_ids(
        definition.story_transitions,
        source=source,
        object_name="story_transition",
    )
    _ensure_unique_ids(
        definition.links,
        source=source,
        object_name="link",
    )
    _ensure_unique_ids(
        definition.endings,
        source=source,
        object_name="ending",
    )

    flag_ids = _ensure_unique_names(
        definition.flags,
        source=source,
        object_name="flag",
    )
    clock_thresholds = {
        clock.id: {threshold.value for threshold in clock.threshold_events}
        for clock in definition.clocks
    }
    npc_ids = _ensure_unique_ids(
        definition.narrative_context.npcs,
        source=source,
        object_name="npc",
    )
    _ensure_unique_ids(
        definition.narrative_context.lorebook_entries,
        source=source,
        object_name="lorebook_entry",
    )
    _ensure_unique_ids(
        definition.narrative_context.safety_boundaries,
        source=source,
        object_name="safety_boundary",
    )

    if definition.entry_scene_id not in scene_ids:
        raise ModuleValidationError(
            f"模组文件 {source} 的 entry_scene_id={definition.entry_scene_id!r} 不存在"
        )
    if definition.entry_stage_id not in story_stage_ids:
        raise ModuleValidationError(
            f"模组文件 {source} 的 entry_stage_id={definition.entry_stage_id!r} 不存在"
        )

    for stage in definition.story_stages:
        _validate_flag_refs(
            stage.required_flags,
            source=source,
            owner=f"story_stage[{stage.id}]",
            flag_ids=flag_ids,
        )

    for link in definition.links:
        if link.from_scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 link[{link.id}] 引用了不存在的 from_scene_id="
                f"{link.from_scene_id!r}"
            )
        if link.to_scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 link[{link.id}] 引用了不存在的 to_scene_id="
                f"{link.to_scene_id!r}"
            )
        _validate_flag_refs(
            link.required_flags,
            source=source,
            owner=f"link[{link.id}]",
            flag_ids=flag_ids,
        )
        _validate_stage_refs(
            link.required_stages,
            source=source,
            owner=f"link[{link.id}]",
            stage_ids=story_stage_ids,
        )

    for action in definition.actions:
        if action.scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 action[{action.id}] 引用了不存在的 scene_id="
                f"{action.scene_id!r}"
            )
        _validate_action_authoring_terms(action, source=source)
        if action.check is not None and skill_templates is not None:
            _validate_action_check_skill(
                action_id=action.id,
                skill_key=action.check.skill_key,
                source=source,
                skill_templates=skill_templates,
            )
        _validate_conditions(
            action.conditions,
            source=source,
            owner=f"action[{action.id}]",
            flag_ids=flag_ids,
            action_ids=action_ids,
            clock_ids=clock_ids,
        )
        _validate_effects(
            action.effects_on_success,
            source=source,
            owner=f"action[{action.id}].effects_on_success",
            flag_ids=flag_ids,
            clock_ids=clock_ids,
        )
        _validate_effects(
            action.effects_on_failure,
            source=source,
            owner=f"action[{action.id}].effects_on_failure",
            flag_ids=flag_ids,
            clock_ids=clock_ids,
        )
        _validate_stage_refs(
            action.required_stages,
            source=source,
            owner=f"action[{action.id}]",
            stage_ids=story_stage_ids,
        )

    for clock in definition.clocks:
        if clock.start > clock.max_value:
            raise ModuleValidationError(
                f"模组文件 {source} 的 clock[{clock.id}] start 不能大于 max_value"
            )

        last_value = -1
        for threshold in clock.threshold_events:
            if threshold.value > clock.max_value:
                raise ModuleValidationError(
                    f"模组文件 {source} 的 clock[{clock.id}] threshold={threshold.value} "
                    f"超过 max_value={clock.max_value}"
                )
            if threshold.value <= last_value:
                raise ModuleValidationError(
                    f"模组文件 {source} 的 clock[{clock.id}] threshold 必须严格递增"
                )
            last_value = threshold.value
            _validate_effects(
                threshold.effects,
                source=source,
                owner=f"clock[{clock.id}].threshold[{threshold.value}]",
                flag_ids=flag_ids,
                clock_ids=clock_ids,
            )

    for ending in definition.endings:
        if ending.scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 ending[{ending.id}] 引用了不存在的 scene_id="
                f"{ending.scene_id!r}"
            )
        _validate_conditions(
            ending.conditions,
            source=source,
            owner=f"ending[{ending.id}]",
            flag_ids=flag_ids,
            action_ids=action_ids,
            clock_ids=clock_ids,
        )

    _validate_story_transitions(
        definition.story_transitions,
        source=source,
        stage_ids=story_stage_ids,
        scene_ids=scene_ids,
        action_ids=action_ids,
        flag_ids=flag_ids,
        clock_ids=clock_ids,
        clock_thresholds=clock_thresholds,
    )
    _validate_narrative_context(
        definition=definition,
        source=source,
        scene_ids=scene_ids,
        story_stage_ids=story_stage_ids,
        action_ids=action_ids,
        npc_ids=npc_ids,
    )


def _ensure_unique_ids(
    objects: Sequence[_HasId],
    *,
    source: Path,
    object_name: str,
) -> set[str]:
    seen: set[str] = set()

    for item in objects:
        item_id = item.id
        if item_id in seen:
            raise ModuleValidationError(
                f"模组文件 {source} 中存在重复的 {object_name} id={item_id!r}"
            )
        seen.add(item_id)
    return seen


def _ensure_unique_names(
    names: Sequence[str],
    *,
    source: Path,
    object_name: str,
) -> set[str]:
    seen: set[str] = set()

    for name in names:
        if name in seen:
            raise ModuleValidationError(
                f"模组文件 {source} 中存在重复的 {object_name}={name!r}"
            )
        seen.add(name)
    return seen


def _validate_conditions(
    conditions: Sequence[ModuleCondition],
    *,
    source: Path,
    owner: str,
    flag_ids: set[str],
    action_ids: set[str],
    clock_ids: set[str],
) -> None:
    for condition in conditions:
        if (
            condition.type in {"flag_set", "flag_unset"}
            and condition.flag not in flag_ids
        ):
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 flag={condition.flag!r}"
            )
        if (
            condition.type == "action_completed"
            and condition.action_id not in action_ids
        ):
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 action_id="
                f"{condition.action_id!r}"
            )
        if condition.type == "clock_at_least" and condition.clock_id not in clock_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 clock_id="
                f"{condition.clock_id!r}"
            )


def _validate_effects(
    effects: Sequence[ModuleEffect],
    *,
    source: Path,
    owner: str,
    flag_ids: set[str],
    clock_ids: set[str],
) -> None:
    for effect in effects:
        if effect.type in {"set_flag", "clear_flag"} and effect.flag not in flag_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 flag={effect.flag!r}"
            )
        if effect.type == "advance_clock" and effect.clock_id not in clock_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 clock_id="
                f"{effect.clock_id!r}"
            )


def _validate_flag_refs(
    flags: Sequence[str],
    *,
    source: Path,
    owner: str,
    flag_ids: set[str],
) -> None:
    for flag in flags:
        if flag not in flag_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 flag={flag!r}"
            )


def _validate_stage_refs(
    stages: Sequence[str],
    *,
    source: Path,
    owner: str,
    stage_ids: set[str],
) -> None:
    for stage_id in stages:
        if stage_id not in stage_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 stage={stage_id!r}"
            )


def _validate_scene_refs(
    scenes: Sequence[str],
    *,
    source: Path,
    owner: str,
    scene_ids: set[str],
) -> None:
    for scene_id in scenes:
        if scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 scene_id={scene_id!r}"
            )


def _validate_action_refs(
    actions: Sequence[str],
    *,
    source: Path,
    owner: str,
    action_ids: set[str],
) -> None:
    for action_id in actions:
        if action_id not in action_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 action_id={action_id!r}"
            )


def _validate_action_authoring_terms(action, *, source: Path) -> None:
    owner = f"action[{action.id}]"
    terms = [*action.aliases, *action.expected_inputs]
    for term in terms:
        if not term.strip():
            raise ModuleValidationError(f"模组文件 {source} 的 {owner} 包含空别名")
    normalized = [term.strip().lower() for term in action.aliases]
    if len(normalized) != len(set(normalized)):
        raise ModuleValidationError(f"模组文件 {source} 的 {owner} 包含重复 alias")


def _validate_action_check_skill(
    *,
    action_id: str,
    skill_key: str,
    source: Path,
    skill_templates: Mapping[str, SkillTemplate],
) -> None:
    template_key, separator, branch_key = skill_key.partition(":")
    template = skill_templates.get(template_key)
    owner = f"action[{action_id}].check.skill_key"
    if template is None:
        raise ModuleValidationError(
            f"模组文件 {source} 的 {owner} 引用了未知技能模板 {template_key!r}"
        )
    if not separator:
        if template.is_branch_skill:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner}={skill_key!r} 缺少分支技能后缀"
            )
        return
    if not branch_key:
        raise ModuleValidationError(
            f"模组文件 {source} 的 {owner}={skill_key!r} 缺少分支技能 key"
        )
    if not template.is_branch_skill:
        raise ModuleValidationError(
            f"模组文件 {source} 的 {owner}={skill_key!r} 不是合法分支技能"
        )
    if template.allow_custom_branch:
        return
    if branch_key not in {option.key for option in template.branch_options}:
        raise ModuleValidationError(
            f"模组文件 {source} 的 {owner}={skill_key!r} 未定义合法分支"
        )


_ALLOWED_COC_KEYS: frozenset[str] = frozenset(
    {"STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"}
)


def _validate_npc_int_dict(
    *,
    npc_id: str,
    data: dict[str, int],
    source: Path,
    owner_key: str,
    allowed_keys: frozenset[str] | None = None,
) -> None:
    """Validate a module NPC int-valued attribute dict (characteristics / skills).

    Args:
        npc_id: the owning NPC id.
        data: raw dict from the YAML module.
        source: module file path (for error messages).
        owner_key: either ``characteristics`` or ``skills``.
        allowed_keys: if provided, each dict key must be in this frozenset.
    """
    owner = f"narrative_context.npcs[{npc_id}].{owner_key}"
    for key, value in data.items():
        if not isinstance(key, str) or not key:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 包含无效 key={key!r}"
            )
        if allowed_keys is not None and key not in allowed_keys:
            kind = "CoC 属性" if owner_key == "characteristics" else owner_key
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 使用了不允许的 {kind} key={key!r}"
            )
        if not isinstance(value, int) or not (0 <= value <= 100):
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner}[{key!r}] 值 {value!r} 无效，"
                "必须为 0..100 整数"
            )


def _validate_npc_characteristics(
    *,
    npc_id: str,
    characteristics: dict[str, int],
    source: Path,
) -> None:
    _validate_npc_int_dict(
        npc_id=npc_id,
        data=characteristics,
        source=source,
        owner_key="characteristics",
        allowed_keys=_ALLOWED_COC_KEYS,
    )


def _validate_npc_skills(
    *,
    npc_id: str,
    skills: dict[str, int],
    source: Path,
) -> None:
    _validate_npc_int_dict(
        npc_id=npc_id,
        data=skills,
        source=source,
        owner_key="skills",
        allowed_keys=None,
    )


def _validate_npc_refs(
    npcs: Sequence[str],
    *,
    source: Path,
    owner: str,
    npc_ids: set[str],
) -> None:
    for npc_id in npcs:
        if npc_id not in npc_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 npc_id={npc_id!r}"
            )


def _validate_narrative_context(
    *,
    definition: ModuleDefinition,
    source: Path,
    scene_ids: set[str],
    story_stage_ids: set[str],
    action_ids: set[str],
    npc_ids: set[str],
) -> None:
    narrative = definition.narrative_context

    for npc in narrative.npcs:
        owner = f"narrative_context.npcs[{npc.id}]"
        _validate_scene_refs(
            npc.active_scene_ids,
            source=source,
            owner=owner,
            scene_ids=scene_ids,
        )
        _validate_stage_refs(
            npc.active_stage_ids,
            source=source,
            owner=owner,
            stage_ids=story_stage_ids,
        )
        if npc.default_scene_id and npc.default_scene_id not in scene_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 引用了不存在的 default_scene_id="
                f"{npc.default_scene_id!r}"
            )
        _validate_npc_characteristics(
            npc_id=npc.id,
            characteristics=npc.characteristics,
            source=source,
        )
        _validate_npc_skills(
            npc_id=npc.id,
            skills=npc.skills,
            source=source,
        )

    for entry in narrative.lorebook_entries:
        owner = f"narrative_context.lorebook_entries[{entry.id}]"
        if not entry.always_on and not (
            entry.keywords
            or entry.scope_scene_ids
            or entry.scope_stage_ids
            or entry.scope_action_ids
            or entry.npc_ids
        ):
            raise ModuleValidationError(
                f"模组文件 {source} 的 {owner} 缺少触发条件；"
                "请设置 keywords/scope_* 或 always_on=true"
            )
        for keyword in entry.keywords:
            if not keyword.strip():
                raise ModuleValidationError(
                    f"模组文件 {source} 的 {owner} 包含空 keyword"
                )
        _validate_scene_refs(
            entry.scope_scene_ids,
            source=source,
            owner=owner,
            scene_ids=scene_ids,
        )
        _validate_stage_refs(
            entry.scope_stage_ids,
            source=source,
            owner=owner,
            stage_ids=story_stage_ids,
        )
        _validate_action_refs(
            entry.scope_action_ids,
            source=source,
            owner=owner,
            action_ids=action_ids,
        )
        _validate_npc_refs(
            entry.npc_ids,
            source=source,
            owner=owner,
            npc_ids=npc_ids,
        )

    for boundary in narrative.safety_boundaries:
        owner = f"narrative_context.safety_boundaries[{boundary.id}]"
        _validate_scene_refs(
            boundary.scope_scene_ids,
            source=source,
            owner=owner,
            scene_ids=scene_ids,
        )
        _validate_stage_refs(
            boundary.scope_stage_ids,
            source=source,
            owner=owner,
            stage_ids=story_stage_ids,
        )


def _validate_story_transitions(
    transitions: Sequence[StoryTransition],
    *,
    source: Path,
    stage_ids: set[str],
    scene_ids: set[str],
    action_ids: set[str],
    flag_ids: set[str],
    clock_ids: set[str],
    clock_thresholds: dict[str, set[int]],
) -> None:
    priority_by_source: dict[str, set[int]] = {}

    for transition in transitions:
        if transition.source_stage_id not in stage_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 story_transition[{transition.id}] 引用了不存在的 "
                f"source_stage_id={transition.source_stage_id!r}"
            )
        if transition.target_stage_id not in stage_ids:
            raise ModuleValidationError(
                f"模组文件 {source} 的 story_transition[{transition.id}] 引用了不存在的 "
                f"target_stage_id={transition.target_stage_id!r}"
            )
        _validate_flag_refs(
            transition.required_flags,
            source=source,
            owner=f"story_transition[{transition.id}]",
            flag_ids=flag_ids,
        )
        _validate_effects(
            transition.effects,
            source=source,
            owner=f"story_transition[{transition.id}].effects",
            flag_ids=flag_ids,
            clock_ids=clock_ids,
        )

        used_priorities = priority_by_source.setdefault(
            transition.source_stage_id,
            set(),
        )
        if transition.priority in used_priorities:
            raise ModuleValidationError(
                f"模组文件 {source} 的 source_stage_id={transition.source_stage_id!r} "
                f"存在重复的 priority={transition.priority}"
            )
        used_priorities.add(transition.priority)

        if transition.trigger_type == "scene_entered":
            if transition.trigger_value not in scene_ids:
                raise ModuleValidationError(
                    f"模组文件 {source} 的 story_transition[{transition.id}] "
                    f"使用了不存在的 scene trigger_value={transition.trigger_value!r}"
                )
            continue

        if transition.trigger_type == "action_succeeded":
            if transition.trigger_value not in action_ids:
                raise ModuleValidationError(
                    f"模组文件 {source} 的 story_transition[{transition.id}] "
                    f"使用了不存在的 action trigger_value={transition.trigger_value!r}"
                )
            continue

        if transition.trigger_type == "clock_threshold_triggered":
            clock_id, separator, threshold_text = transition.trigger_value.partition(
                ":"
            )
            if separator != ":" or not threshold_text.isdigit():
                raise ModuleValidationError(
                    f"模组文件 {source} 的 story_transition[{transition.id}] "
                    "使用了非法的 clock trigger_value，格式应为 clock_id:threshold"
                )
            if clock_id not in clock_ids:
                raise ModuleValidationError(
                    f"模组文件 {source} 的 story_transition[{transition.id}] "
                    f"使用了不存在的 clock_id={clock_id!r}"
                )
            threshold = int(threshold_text)
            if threshold not in clock_thresholds.get(clock_id, set()):
                raise ModuleValidationError(
                    f"模组文件 {source} 的 story_transition[{transition.id}] "
                    f"引用了未定义的 clock threshold={transition.trigger_value!r}"
                )

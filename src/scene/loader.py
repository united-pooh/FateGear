"""YAML 模组定义加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from collections.abc import Sequence

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from scene.module_definition import ModuleDefinition
from scene.module_types import ModuleCondition, ModuleEffect
from scene.story import StoryTransition

MODULE_ROOT = Path(__file__).resolve().parents[2] / "module"


class _HasId(Protocol):
    id: str


class ModuleValidationError(ValueError):
    """模组结构或语义校验失败。"""


def load_module_definition(path: str | Path) -> ModuleDefinition:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"未找到模组文件: {file_path}")

    raw_text = file_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw_text) or {}

    try:
        definition = ModuleDefinition.model_validate(payload)
    except ValidationError as exc:
        raise ModuleValidationError(
            f"模组文件 {file_path} 结构校验失败: {exc}"
        ) from exc

    _validate_module_definition(definition=definition, source=file_path)
    return definition


def load_module_by_id(
    module_id: str,
    *,
    module_root: str | Path | None = None,
) -> ModuleDefinition:
    root = Path(module_root) if module_root is not None else MODULE_ROOT
    return load_module_definition(root / module_id / "module.yaml")


def _validate_module_definition(
    *,
    definition: ModuleDefinition,
    source: Path,
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
            clock_id, separator, threshold_text = transition.trigger_value.partition(":")
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

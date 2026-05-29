from __future__ import annotations

from pathlib import Path

import pytest

from scenario.io import load_module_by_id, load_module_definition
from scenario.module import ModuleValidationError


def test_load_sample_modules_from_yaml() -> None:
    generic = load_module_by_id("generic_mvp")
    tokoyami = load_module_by_id("tokoyami_subset")

    assert generic.entry_scene_id == "foyer"
    assert generic.entry_stage_id == "setup"
    assert generic.action_map()["prime_machine"].scene_id == "control"
    assert generic.story_transitions[0].id == "unlock_access"
    assert tokoyami.clock_map()["rear_threat"].max_value == 10
    assert tokoyami.story_stage_map()["awake"].name == "惊醒"
    assert tokoyami.endings[0].id == "true_end"
    assert generic.narrative_context.worldview_brief == ""


def test_loader_accepts_narrative_context_fields(tmp_path: Path) -> None:
    module_file = tmp_path / "module.yaml"
    module_file.write_text(
        """
module_id: narrative_context_ok
title: 叙事上下文测试
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
    description: 车窗外没有城市，只有像潮水一样退去的灯。
links: []
actions:
  - id: inspect_window
    scene_id: start
    name: 查看车窗
    kind: investigate
clocks: []
story_stages:
  - id: intro
    name: 开场
story_transitions: []
endings: []
narrative_context:
  worldview_brief: 末班车驶入一段不属于现实的轨道。
  max_lore_entries: 3
  max_context_chars: 1200
  npcs:
    - id: attendant
      name: 沉默的乘务员
      role: 引导者
      public_description: 制服袖口沾着干涸的雨水。
      persona: 温和但回避关键问题。
      speaking_style: 短句，像在确认每个字是否安全。
      active_scene_ids: [start]
      secrets: [她知道列车没有终点。]
  lorebook_entries:
    - id: night_train_signal
      title: 夜车信号
      content: 信号灯每闪三次，车厢都会短暂显出另一层年代。
      keywords: [信号灯]
      scope_scene_ids: [start]
      scope_action_ids: [inspect_window]
      priority: 200
      insertion_order: 10
  safety_boundaries:
    - id: no_real_minor_harm
      severity: hard
      note: 避免描写现实儿童受害细节。
  atmosphere:
    tone: 潮湿、压抑、带有被观察感。
    sensory_palette: [铁锈味, 冷光, 玻璃震颤]
    style_rules: [先给可观察事实，再给不安解释。]
  prose_controls:
    paragraph_limit: 2
    horror_intensity: 4
    dice_visibility: summarize
""".strip(),
        encoding="utf-8",
    )

    definition = load_module_definition(module_file)

    assert definition.narrative_context.worldview_brief.startswith("末班车")
    assert definition.npc_map()["attendant"].name == "沉默的乘务员"
    assert definition.lorebook_entry_map()["night_train_signal"].priority == 200
    assert definition.narrative_context.prose_controls.paragraph_limit == 2


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            """
module_id: invalid_duplicate_scene
title: 重复场景
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
  - id: start
    name: 重复起点
links: []
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "重复的 scene id",
        ),
        (
            """
module_id: invalid_link_scene
title: 坏连线
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links:
  - id: missing_target
    from_scene_id: start
    to_scene_id: nowhere
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "to_scene_id",
        ),
        (
            """
module_id: invalid_action_scene
title: 坏动作
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions:
  - id: inspect
    scene_id: nowhere
    name: 检查
    kind: investigate
    once: true
    effects_on_success:
      - type: set_flag
        flag: ready
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "scene_id",
        ),
        (
            """
module_id: invalid_unknown_skill
title: 坏技能
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions:
  - id: inspect
    scene_id: start
    name: 检查
    kind: investigate
    check:
      skill_key: impossible_skill
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "未知技能模板",
        ),
        (
            """
module_id: invalid_branch_skill
title: 坏分支技能
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions:
  - id: inspect
    scene_id: start
    name: 检查
    kind: investigate
    check:
      skill_key: science
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "缺少分支技能后缀",
        ),
        (
            """
module_id: invalid_duplicate_alias
title: 重复动作别名
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions:
  - id: inspect
    scene_id: start
    name: 检查
    kind: investigate
    aliases: [检查, 检查]
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "重复 alias",
        ),
        (
            """
module_id: invalid_clock_ref
title: 坏时钟引用
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions:
  - id: inspect
    scene_id: start
    name: 检查
    kind: investigate
    once: true
    effects_on_success:
      - type: advance_clock
        clock_id: missing_clock
        value: 1
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
""",
            "clock_id",
        ),
        (
            """
module_id: invalid_duplicate_npc
title: 重复 NPC
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
narrative_context:
  npcs:
    - id: guide
      name: 向导甲
    - id: guide
      name: 向导乙
""",
            "重复的 npc id",
        ),
        (
            """
module_id: invalid_lore_scene
title: 坏世界书引用
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
narrative_context:
  lorebook_entries:
    - id: wrong_scene
      title: 不存在的场景
      content: 这条不该加载成功。
      scope_scene_ids: [missing]
""",
            "scene_id",
        ),
        (
            """
module_id: invalid_lore_trigger
title: 无触发世界书
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
endings: []
narrative_context:
  lorebook_entries:
    - id: no_trigger
      title: 没有触发条件
      content: 没有触发条件就会变成无节制 prompt 堆叠。
""",
            "缺少触发条件",
        ),
    ],
)
def test_loader_rejects_invalid_module_definitions(
    tmp_path: Path,
    payload: str,
    expected_message: str,
) -> None:
    module_file = tmp_path / "module.yaml"
    module_file.write_text(payload.strip(), encoding="utf-8")

    with pytest.raises(ModuleValidationError, match=expected_message):
        load_module_definition(module_file)


def test_loader_rejects_story_transition_with_unknown_target_stage(
    tmp_path: Path,
) -> None:
    module_file = tmp_path / "module.yaml"
    module_file.write_text(
        """
module_id: invalid_story_transition
title: 坏剧情迁移
version: 1
entry_scene_id: start
entry_stage_id: intro
flags: [ready]
scenes:
  - id: start
    name: 起点
links: []
actions: []
clocks: []
story_stages:
  - id: intro
    name: 开场
story_transitions:
  - id: broken_transition
    source_stage_id: intro
    target_stage_id: missing_stage
    trigger_type: action_succeeded
    trigger_value: inspect
endings: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ModuleValidationError, match="target_stage_id"):
        load_module_definition(module_file)

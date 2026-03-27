from __future__ import annotations

from pathlib import Path

import pytest

from scene.loader import (
    ModuleValidationError,
    load_module_by_id,
    load_module_definition,
)


def test_load_sample_modules_from_yaml() -> None:
    generic = load_module_by_id("generic_mvp")
    tokoyami = load_module_by_id("tokoyami_subset")

    assert generic.entry_scene_id == "foyer"
    assert generic.action_map()["prime_machine"].scene_id == "control"
    assert tokoyami.clock_map()["rear_threat"].max_value == 10
    assert tokoyami.endings[0].id == "true_end"


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            """
module_id: invalid_duplicate_scene
title: 重复场景
version: 1
entry_scene_id: start
flags: [ready]
scenes:
  - id: start
    name: 起点
  - id: start
    name: 重复起点
links: []
actions: []
clocks: []
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
endings: []
""",
            "scene_id",
        ),
        (
            """
module_id: invalid_clock_ref
title: 坏时钟引用
version: 1
entry_scene_id: start
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
endings: []
""",
            "clock_id",
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

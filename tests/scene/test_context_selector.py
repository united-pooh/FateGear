from __future__ import annotations

from scenario.context import NarrativeContextSelector
from scenario.io import load_module_by_id
from scenario.module.models import ModuleLorebookEntry, ModuleNarrativeContext
from scenario.runtime import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


def test_context_selector_orders_lore_by_priority_before_yaml_order() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    narrative = ModuleNarrativeContext(
        max_lore_entries=3,
        max_context_chars=1200,
        lorebook_entries=[
            ModuleLorebookEntry(
                id="low_priority",
                title="低优先级",
                content="这条写在前面，但不应该先进入 prompt。",
                always_on=True,
                priority=10,
            ),
            ModuleLorebookEntry(
                id="high_priority",
                title="高优先级",
                content="这条优先级更高，应该排在最前。",
                always_on=True,
                priority=900,
            ),
        ],
    )
    module = module.model_copy(update={"narrative_context": narrative})

    context = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_6",
    )

    assert [entry.entry_id for entry in context.selected_lorebook_entries] == [
        "high_priority",
        "low_priority",
    ]


def test_context_selector_records_budget_and_count_skip_reasons() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    narrative = ModuleNarrativeContext(
        worldview_brief="短世界观。",
        max_lore_entries=2,
        max_context_chars=220,
        lorebook_entries=[
            ModuleLorebookEntry(
                id="selected_a",
                title="可进入",
                content="短条目。",
                always_on=True,
                priority=900,
            ),
            ModuleLorebookEntry(
                id="budget_skipped",
                title="预算跳过",
                content="这是一段很长的条目。" * 80,
                always_on=True,
                priority=850,
            ),
            ModuleLorebookEntry(
                id="selected_b",
                title="可进入二",
                content="短条目二。",
                always_on=True,
                priority=800,
            ),
            ModuleLorebookEntry(
                id="count_skipped",
                title="数量跳过",
                content="短条目三。",
                always_on=True,
                priority=700,
            ),
        ],
    )
    module = module.model_copy(update={"narrative_context": narrative})

    context = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_6",
    )

    assert [entry.entry_id for entry in context.selected_lorebook_entries] == [
        "selected_a",
        "selected_b",
    ]
    assert context.skipped_ids["lore:budget_skipped"] == "context_budget_exceeded"
    assert context.skipped_ids["lore:count_skipped"] == "max_lore_entries_reached"

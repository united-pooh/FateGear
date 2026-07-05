from __future__ import annotations

from scenario.context import NarrativeContextSelector
from scenario.context.models import SelectedNPCContext
from scenario.io import load_module_by_id
from scenario.module.models import (
    ModuleLorebookEntry,
    ModuleNarrativeContext,
)
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


def test_context_selector_does_not_select_action_scoped_lore_for_observe() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    context = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_6",
        pending_intents={"p1": {"type": "observe", "text": "环绕四周环境"}},
        include_keeper=False,
    )

    assert "lore:note_warning" not in context.selected_ids
    assert context.skipped_ids["lore:note_warning"] == "trigger_not_matched"


def test_context_selector_selects_action_scoped_lore_for_matching_action() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    context = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_6",
        pending_intents={"p1": {"type": "action", "action_id": "inspect_note"}},
        include_keeper=False,
    )

    assert [entry.entry_id for entry in context.selected_lorebook_entries] == [
        "note_warning"
    ]
    assert context.selected_lorebook_entries[0].scope_action_ids == ["inspect_note"]


def test_authoritative_position_priority() -> None:
    """TASK-012: NPC moved into car_5 by the runtime must be selected when querying
    car_5 — even if its static active_scene_ids only reference other scenes — and must
    not be selected when querying car_6."""
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    npc_id = next(iter(module.npc_map()))

    # Move the NPC into car_5 by authoritative session state.
    session.npc_states[npc_id].current_scene_id = "car_5"

    selector = NarrativeContextSelector()

    # car_5 should see that NPC now.
    ctx = selector.select(
        module=module,
        session=session,
        scene_id="car_5",
    )
    selected_ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert npc_id in selected_ids
    matching = next(npc for npc in ctx.selected_npcs if npc.npc_id == npc_id)
    assert matching.selection_reason == "authoritative_scene_placement"

    # car_6 should NOT see it (authoritative_out_of_scope skip).
    ctx_other = selector.select(
        module=module,
        session=session,
        scene_id="car_6",
    )
    other_ids = [npc.npc_id for npc in ctx_other.selected_npcs]
    assert npc_id not in other_ids
    assert ctx_other.skipped_ids[f"npc:{npc_id}"] == "authoritative_out_of_scope"


def test_fallback_to_active_scene_ids_when_current_scene_id_empty() -> None:
    """TASK-013: When the NPC has no authoritative current_scene_id, the static
    active_scene_ids / active_stage_ids fallback is used."""
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    npc_id = "attendant"
    # Ensure authoritative state is empty so fallback applies.
    session.npc_states[npc_id].current_scene_id = ""
    # Ensure current_stage_id matches an active stage for the attendant NPC.
    session.story_state.current_stage_id = "awake"

    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_keeper=False,
    )
    selected_ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert npc_id in selected_ids
    matching = next(npc for npc in ctx.selected_npcs if npc.npc_id == npc_id)
    assert matching.selection_reason in {
        "scene_scope",
        "stage_scope",
        "scene_and_stage_scope",
        "global_npc",
    }


def test_selected_npc_context_fields_unchanged() -> None:
    """TASK-012/TASK-013: SelectedNPCContext schema must remain exactly the same."""
    expected = {
        "npc_id",
        "name",
        "role",
        "public_description",
        "persona",
        "speaking_style",
        "goals",
        "knowledge_boundary",
        "secrets",
        "visibility",
        "selection_reason",
    }
    assert set(SelectedNPCContext.model_fields.keys()) == expected


# ---------------------------------------------------------------------------
# TASK-0XX: per-player NPC visibility filter (_npc_visible_to_players)
# ---------------------------------------------------------------------------

def _make_runtime_with_npc_visibility(
    npc_id: str,
    visible_to: set[str],
) -> tuple:
    """Build a tokoyami_subset session with *npc_id* having visible_to_player_ids."""
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset", ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )
    module = load_module_by_id("tokoyami_subset")

    # Flag the target NPC for per-player visibility: attendant originally lives in
    # car_4 with visible_to={"p1"} — keep authoritative placement matching car_4
    # so it's selected by the scene filter, and override visible_to_player_ids.
    session.npc_states[npc_id].visible_to_player_ids = set(visible_to)
    # Ensure stage also matches so fallback-authoritative branch keeps it chosen.
    if not session.npc_states[npc_id].current_scene_id:
        session.npc_states[npc_id].current_scene_id = "car_4"
    return runtime, session, module


def _make_runtime_permissive_fixture() -> tuple:
    """Build a session where attendant has a pristine (permissive) setup without per-player scoping."""
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset", ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    # attendant starts as current_scene=car_4, visible_to={p1} — leave as-is for permissive test.
    return runtime, session, module


def test_per_player_visibility_disjoint_filtered() -> None:
    """An NPC scoped to p2 must be filtered when include_players=['p1']."""
    _, session, module = _make_runtime_with_npc_visibility("attendant", {"p2"})
    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_players=["p1"],
    )
    ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert "attendant" not in ids
    assert ctx.skipped_ids["npc:attendant"] == "player_visibility_filtered"


def test_per_player_visibility_intersecting_passes() -> None:
    """An NPC scoped to p1,p2 must pass when include_players=['p2']."""
    _, session, module = _make_runtime_with_npc_visibility("attendant", {"p1", "p2"})
    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_players=["p2"],
    )
    ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert "attendant" in ids


def test_per_player_visibility_no_session_entry_permissive() -> None:
    """NPC with no per-player scope is permissively selected even for unknown players."""
    _, session, module = _make_runtime_permissive_fixture()
    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_players=["p99"],  # player not in visible_to
    )
    ids = [npc.npc_id for npc in ctx.selected_npcs]
    # attendant's visible_to={"p1"}, include_players=["p99"] — disjoint → FILTERED.
    assert "attendant" not in ids
    assert ctx.skipped_ids["npc:attendant"] == "player_visibility_filtered"


def test_per_player_visibility_empty_visible_set_permissive() -> None:
    """NPC with visible_to_player_ids=set() is permissively included."""
    _, session, module = _make_runtime_with_npc_visibility("attendant", set())
    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_players=["p1"],
    )
    ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert "attendant" in ids


def test_per_player_visibility_bypassed_when_none() -> None:
    """include_players=None means the filter is bypassed — even disjoint players pass."""
    _, session, module = _make_runtime_with_npc_visibility("attendant", {"p99"})
    ctx = NarrativeContextSelector().select(
        module=module,
        session=session,
        scene_id="car_4",
        include_players=None,  # bypass
    )
    ids = [npc.npc_id for npc in ctx.selected_npcs]
    assert "attendant" in ids  # filter bypassed when include_players=None
    assert "npc:attendant" not in ctx.skipped_ids  # no skip record written

from __future__ import annotations

from scenario.agent import PromptBuilder
from scenario.agent.plan_agent import _build_system_message, _build_user_message
from scenario.agent.render_agent import (
    _build_render_system_prompt,
    _build_render_user_message,
)
from scenario.agent.models import CommitResult
from scenario.io import load_module_by_id
from scenario.runtime import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


def test_prompt_builder_prefers_explicit_pending_intent_snapshot() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")
    builder = PromptBuilder()

    prompt = builder.build(
        session=session,
        module=module,
        scene_id="foyer",
        pending_intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )

    assert len(prompt.pending_intents) == 1
    assert prompt.pending_intents[0].player_id == "p1"
    assert prompt.pending_intents[0].target_scene_id == "storage"


def test_prompt_builder_selects_npc_lore_and_kp_style_context() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")
    builder = PromptBuilder()

    prompt = builder.build(
        session=session,
        module=module,
        scene_id="car_6",
        pending_intents={"p1": {"type": "action", "action_id": "inspect_note"}},
    )

    assert prompt.module.worldview_brief.startswith("常暗列车")
    assert [entry.entry_id for entry in prompt.narrative.selected_lorebook_entries] == [
        "note_warning"
    ]
    assert prompt.narrative.prose_controls.paragraph_limit == 3
    assert "铁轨震颤" in prompt.narrative.atmosphere.sensory_palette

    system_message = _build_system_message(prompt)
    user_message = _build_user_message(prompt)

    assert "只读叙事上下文" in system_message
    assert "密闭、潮湿" in system_message
    assert "门上便签" in user_message
    assert "lore:note_warning" in user_message


def test_prompt_builder_keeps_keeper_only_lore_out_of_public_render_context() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.story_state.current_stage_id = "informed"
    session.player_states["p1"].current_scene_id = "car_3"
    module = load_module_by_id("tokoyami_subset")
    builder = PromptBuilder()

    keeper_context = builder.build_narrative_context(
        session=session,
        module=module,
        scene_id="car_3",
        include_keeper=True,
    )
    public_context = builder.build_narrative_context(
        session=session,
        module=module,
        scene_id="car_3",
        include_keeper=False,
    )

    assert [entry.entry_id for entry in keeper_context.selected_lorebook_entries] == [
        "rear_threat_texture"
    ]
    assert public_context.selected_lorebook_entries == []
    assert public_context.skipped_ids["lore:rear_threat_texture"] == "keeper_only"

    commit = CommitResult(
        session_id=session.session_id,
        turn_no=session.current_turn,
        scene_id="car_3",
        event_summary=["调查员翻动了行李堆。"],
        narrative=public_context,
    )
    render_system = _build_render_system_prompt(commit)
    render_user = _build_render_user_message(commit)

    assert "后方的大嘴" not in render_system
    assert "后方的大嘴" not in render_user
    assert "禁止提前揭示" in render_system


def test_render_prompt_keeps_freeform_from_becoming_scene_movement() -> None:
    commit = CommitResult(
        session_id="s1",
        turn_no=1,
        scene_id="car_6",
        scene_name="6号车厢",
        scene_description="末班车的起始车厢，门上贴着便签。",
        outcomes=[
            {
                "player_id": "p1",
                "intent_type": "freeform",
                "success": True,
                "freeform_text": "我偏要往后方声音来源走过去看看",
            }
        ],
    )

    render_system = _build_render_system_prompt(commit)
    render_user = _build_render_user_message(commit)

    assert "除非本轮裁定结果里有成功的 move" in render_system
    assert "不得叙述成已经移动到其他场景" in render_user

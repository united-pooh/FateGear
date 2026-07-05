from __future__ import annotations

from scenario.agent import PromptBuilder
from scenario.agent.plan_agent import _build_system_message, _build_user_message
from scenario.agent.render_agent import (
    _build_render_system_prompt,
    _build_render_user_message,
)
from scenario.agent.models import CommitResult
from scenario.context.models import SelectedNPCContext
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


def test_render_prompt_preserves_rear_threat_distance_continuity() -> None:
    commit = CommitResult(
        session_id="s1",
        turn_no=6,
        scene_id="car_6",
        scene_name="6号车厢",
        applied_clock_deltas={"rear_threat": 4},
        clock_values={"rear_threat": 10},
        resolved_ending="bad_end",
        outcomes=[
            {
                "player_id": "p1",
                "intent_type": "freeform",
                "success": False,
                "freeform_text": "不顾一切大步跑起来",
                "effects_applied": ["运行时推进时钟:rear_threat+3"],
            }
        ],
    )

    render_system = _build_render_system_prompt(commit)
    render_user = _build_render_user_message(commit)

    assert "威胁距离连续性" in render_system
    assert "rear_threat" in render_user
    assert "被追上/吞没" in render_user
    assert "运行时推进时钟:rear_threat+3" in render_user


def test_plan_prompt_marks_off_map_freeform_as_boundary_attempt() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = "car_4"
    module = load_module_by_id("tokoyami_subset")
    builder = PromptBuilder()

    prompt = builder.build(
        session=session,
        module=module,
        scene_id="car_4",
        pending_intents={
            "p1": {
                "type": "freeform",
                "text": "我想尝试前往七号车厢",
                "freeform_kind": "off_map_move",
                "intended_target": "七号车厢",
                "risk_hint": "玩家正在尝试前往模组场景图未定义或当前不可达的危险边界。",
            }
        },
    )
    user_message = _build_user_message(prompt)

    assert prompt.pending_intents[0].freeform_kind == "off_map_move"
    assert prompt.pending_intents[0].intended_target == "七号车厢"
    assert "自由行动类型=off_map_move" in user_message
    assert "意图目标=七号车厢" in user_message
    assert "危险边界" in user_message


def test_prompt_builder_injects_illegal_move_risk_as_read_only_fact() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    risk = session.player_states["p1"].illegal_move_risk
    risk.illegal_value = 8
    risk.consecutive_count = 2
    risk.total_count = 3
    risk.recent_window_count = 3
    risk.last_violation_turn = 4
    risk.last_penalty_tier = "major_penalty"

    prompt = PromptBuilder().build(
        session=session,
        module=load_module_by_id("generic_mvp"),
        scene_id="foyer",
    )

    risk_fact = prompt.spatial.illegal_move_risk["p1"]
    assert risk_fact["illegal_value"] == 8
    assert risk_fact["last_penalty_tier"] == "major_penalty"
    assert risk_fact["major_threshold"] == 7
    assert risk_fact["severe_threshold"] == 10
    assert risk_fact["next_threshold"] == {"tier": "severe_penalty", "value": 10}
    assert risk_fact["current_intent_classification"] == {}

    user_message = _build_user_message(prompt)
    assert "越界移动风险（只读运行时事实，Agent 不得覆盖）" in user_message
    assert "p1: illegal_value=8" in user_message
    assert "next_threshold=severe_penalty:10" in user_message


def test_prompt_builder_previews_pending_off_map_move_risk_update() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.current_turn = 2
    risk = session.player_states["p1"].illegal_move_risk
    risk.illegal_value = 3
    risk.consecutive_count = 1
    risk.total_count = 1
    risk.recent_window_count = 1
    risk.last_violation_turn = 1
    risk.last_penalty_tier = "warning"

    prompt = PromptBuilder().build(
        session=session,
        module=load_module_by_id("generic_mvp"),
        scene_id="foyer",
        pending_intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )

    classification = prompt.spatial.illegal_move_risk["p1"][
        "current_intent_classification"
    ]
    assert classification["from_scene_id"] == "foyer"
    assert classification["target_scene_id"] == "exit"
    assert classification["reason_code"] == "no_link"
    assert classification["violation_kind"] == "off_map_move"
    assert classification["risk_preview"] == {
        "score_before": 3,
        "score_after": 9,
        "delta": 6,
        "consecutive_count": 2,
        "penalty_tier": "major_penalty",
        "threshold_crossed": "major_penalty",
        "required_threshold": 7,
        "heavy_punishment_required": True,
    }

    user_message = _build_user_message(prompt)
    assert "current_move=foyer->exit" in user_message
    assert "reason_code=no_link" in user_message
    assert "violation_kind=off_map_move" in user_message
    assert "preview=3->9" in user_message
    assert "heavy_required=True" in user_message


def test_selected_npc_context_schema_stable_in_prompt_pipeline() -> None:
    """TASK-012/TASK-013: pipeline consumer relies on SelectedNPCContext schema — must
    remain identical across prompt-builder flows."""
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

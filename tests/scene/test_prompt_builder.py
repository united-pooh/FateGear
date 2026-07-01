from __future__ import annotations

from scenario.agent import PromptBuilder
from scenario.agent.plan_agent import _build_user_message
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

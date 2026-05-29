from __future__ import annotations

from scenario.intent import IntentNormalizer
from scenario.io import load_module_by_id
from scenario.runtime import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


def test_intent_normalizer_matches_reachable_scene_by_natural_text() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我想去储藏室看看",
    )

    assert result.accepted is True
    assert result.intent_payload == {"type": "move", "target_scene_id": "storage"}
    assert result.matched_kind == "move"


def test_intent_normalizer_matches_action_alias_in_current_scene() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = "storage"
    module = load_module_by_id("generic_mvp")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我翻箱子找钥匙",
    )

    assert result.accepted is True
    assert result.intent_payload == {"type": "action", "action_id": "find_key"}
    assert result.matched_kind == "action"


def test_intent_normalizer_returns_clarification_for_unknown_text() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我开始跳舞",
    )

    assert result.accepted is False
    assert "请明确" in result.clarification_question
    assert "移动到「储藏室」" in result.candidates

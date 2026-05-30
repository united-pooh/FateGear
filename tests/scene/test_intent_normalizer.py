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
        raw_text="随便来点什么",
    )

    assert result.accepted is False
    assert "请明确" in result.clarification_question
    assert "移动到「储藏室」" in result.candidates
    assert "观察当前环境" in result.candidates


def test_intent_normalizer_clarifies_equal_action_candidates_by_naming_them() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = "storage"
    session.global_flags.add("key_found")
    module = load_module_by_id("generic_mvp")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="钥匙",
    )

    assert result.accepted is False
    assert "多个同样可信的候选" in result.clarification_question
    assert "执行「搜索钥匙」" in result.clarification_question
    assert "执行「解锁控制室」" in result.clarification_question


def test_intent_normalizer_accepts_wait_without_forcing_progression() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我先原地等一下，保持警惕",
    )

    assert result.accepted is True
    assert result.intent_payload == {
        "type": "observe",
        "text": "我先原地等一下，保持警惕",
    }
    assert result.matched_kind == "observe"
    assert result.matched_id == "freeform"
    assert result.match_basis == ["observe:freeform:0.57"]


def test_intent_normalizer_accepts_unexpected_low_risk_action_as_observe() -> None:
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

    assert result.accepted is True
    assert result.intent_payload == {"type": "observe", "text": "我开始跳舞"}
    assert result.matched_kind == "observe"
    assert result.matched_id == "freeform"
    assert result.candidates == ["执行非推进自由行动"]


def test_intent_normalizer_accepts_observe_without_forcing_progression() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="环绕四周，查看周围环境",
    )

    assert result.accepted is True
    assert result.intent_payload == {
        "type": "observe",
        "text": "环绕四周，查看周围环境",
    }
    assert result.matched_kind == "observe"


def test_intent_normalizer_accepts_checking_current_situation_as_observe() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我只是想确认一下什么情况",
    )

    assert result.accepted is True
    assert result.intent_payload == {
        "type": "observe",
        "text": "我只是想确认一下什么情况",
    }
    assert result.matched_kind == "observe"


def test_intent_normalizer_accepts_corridor_move_and_look_without_generic_ambiguity() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("tokoyami_subset")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="去车厢尽头廊道仔细查看一下",
    )

    assert result.accepted is True
    assert result.clarification_question == ""
    assert result.intent_payload == {"type": "move", "target_scene_id": "car_4"}
    assert result.matched_kind == "move"
    assert "观察当前环境" not in result.candidates
    assert result.match_basis == ["move:car_4:0.72", "observe:deferred:0.67"]
    assert result.deferred_intents == [
        {
            "type": "observe",
            "text": "去车厢尽头廊道仔细查看一下",
            "after": "move",
            "reason": "移动后继续观察目标场景；本回合不会因此自动揭示未触发线索。",
            "confidence": 0.67,
        }
    ]

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
    assert "自由观察/行动" in result.candidates


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
        "type": "freeform",
        "text": "我先原地等一下，保持警惕",
    }
    assert result.matched_kind == "freeform"
    assert result.matched_id == "freeform"
    assert result.match_basis == ["freeform:freeform:0.57"]


def test_intent_normalizer_accepts_unexpected_low_risk_action_as_freeform() -> None:
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
    assert result.intent_payload == {"type": "freeform", "text": "我开始跳舞"}
    assert result.matched_kind == "freeform"
    assert result.matched_id == "freeform"
    assert result.candidates == ["尝试自由行动"]


def test_intent_normalizer_accepts_observe_as_freeform_without_forcing_progression() -> None:
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
        "type": "freeform",
        "text": "环绕四周，查看周围环境",
    }
    assert result.matched_kind == "freeform"
    assert result.matched_id == "observe"


def test_intent_normalizer_accepts_checking_current_situation_as_freeform() -> None:
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
        "type": "freeform",
        "text": "我只是想确认一下什么情况",
    }
    assert result.matched_kind == "freeform"
    assert result.matched_id == "observe"


def test_intent_normalizer_accepts_window_look_as_freeform() -> None:
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
        raw_text="从车窗往外看",
    )

    assert result.accepted is True
    assert result.intent_payload == {"type": "freeform", "text": "从车窗往外看"}
    assert result.matched_kind == "freeform"
    assert result.matched_id == "observe"


def test_intent_normalizer_accepts_moving_toward_sound_as_freeform() -> None:
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
        raw_text="我偏要往后方声音来源走过去看看",
    )

    assert result.accepted is True
    assert result.intent_payload == {
        "type": "freeform",
        "text": "我偏要往后方声音来源走过去看看",
    }
    assert result.matched_kind == "freeform"
    assert result.matched_id == "freeform"


def test_intent_normalizer_accepts_physical_sensory_action_as_freeform() -> None:
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
        raw_text="我趴到地板上闻铁轨下面的味道",
    )

    assert result.accepted is True
    assert result.intent_payload == {
        "type": "freeform",
        "text": "我趴到地板上闻铁轨下面的味道",
    }
    assert result.matched_kind == "freeform"
    assert result.matched_id == "freeform"


def test_intent_normalizer_defers_narrated_object_manipulation_to_llm() -> None:
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
        raw_text="我申请尝试破坏这个金属隔板，周围有没有什么趁手的工具",
    )

    assert result.accepted is False
    assert result.intent_payload is None
    assert result.clarification_question
    assert "自由观察/行动" in result.candidates


def test_intent_normalizer_accepts_off_map_car_as_freeform_boundary() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = "car_4"
    session.story_state.current_stage_id = "informed"
    session.global_flags.add("note_read")
    module = load_module_by_id("tokoyami_subset")

    result = IntentNormalizer().normalize(
        runtime=runtime,
        session=session,
        module=module,
        player_id="p1",
        raw_text="我想尝试前往七号车厢",
    )

    assert result.accepted is True
    assert result.intent_payload is not None
    assert result.intent_payload["type"] == "freeform"
    assert result.intent_payload["text"] == "我想尝试前往七号车厢"
    assert result.intent_payload["freeform_kind"] == "off_map_move"
    assert result.intent_payload["intended_target"] == "七号车厢"
    assert "危险边界" in str(result.intent_payload["risk_hint"])
    assert result.matched_kind == "freeform"
    assert result.matched_id == "off_map_move"
    assert result.candidates == ["尝试前往未知区域「七号车厢」"]
    assert result.match_basis == ["freeform:off_map_move:0.76"]


def test_intent_normalizer_accepts_location_question_as_freeform_for_api() -> None:
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
        raw_text="我在哪里",
    )

    assert result.accepted is True
    assert result.intent_payload == {"type": "freeform", "text": "我在哪里"}
    assert result.matched_kind == "freeform"
    assert result.matched_id == "observe"


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
    assert "自由观察/行动" not in result.candidates
    assert result.match_basis == ["move:car_4:0.72", "freeform:deferred_observe:0.67"]
    assert result.deferred_intents == [
        {
            "type": "freeform",
            "text": "去车厢尽头廊道仔细查看一下",
            "after": "move",
            "subtype": "observe",
            "reason": "移动后继续进行自由观察；本回合不会因此自动揭示未触发线索。",
            "confidence": 0.67,
        }
    ]

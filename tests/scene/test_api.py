from __future__ import annotations

import asyncio

import pytest

from scenario.api import ScenarioService
from scenario.runtime import SceneRuntime


def test_scenario_service_lists_sample_modules() -> None:
    service = ScenarioService()

    modules = service.list_modules()

    assert [module.module_id for module in modules] == [
        "generic_mvp",
        "tokoyami_subset",
    ]


def test_scenario_service_can_create_party_and_join_multiple_players() -> None:
    service = ScenarioService()

    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    joined = service.join_party(created.session_id, {"player_id": "p2"})
    latest = service.get_party(created.session_id)

    assert created.status == "waiting"
    assert created.owner_id == "keeper"
    assert [player.player_id for player in created.players] == ["keeper"]
    assert [player.player_id for player in joined.players] == ["keeper", "p2"]
    assert latest.session_id == created.session_id
    assert latest.current_stage_id == "setup"
    assert latest.players[1].current_scene_id == "foyer"


def test_scenario_service_rejects_duplicate_player_join() -> None:
    service = ScenarioService()
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    with pytest.raises(ValueError, match="已经在会话"):
        service.join_party(created.session_id, {"player_id": "keeper"})


def test_scenario_service_creates_long_player_id_with_safe_default_name() -> None:
    service = ScenarioService()
    player_id = "x" * 30

    created = service.create_party(
        {"module_id": "generic_mvp", "creator_id": player_id}
    )
    session = service._runtime.get_session(created.session_id)

    assert created.owner_id == player_id
    assert len(session.player_states[player_id].investigator.name) <= 30


def test_scenario_service_mounts_default_module_skills() -> None:
    service = ScenarioService()
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    session = service._runtime.get_session(created.session_id)
    skills = session.player_states["keeper"].investigator.skills

    assert {"spot_hidden", "art_craft:locksmith", "science:physics"} <= set(skills)


def test_scenario_service_submit_intent_and_resolve_turn() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    submitted = service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "move", "target_scene_id": "storage"},
        },
    )
    first_resolution = asyncio.run(service.resolve_turn(created.session_id))
    service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "action", "action_id": "find_key"},
        },
    )
    second_resolution = asyncio.run(service.resolve_turn(created.session_id))
    latest = service.get_party(created.session_id)

    assert submitted.pending_players == ["keeper"]
    assert first_resolution.next_turn == 2
    assert second_resolution.turn_no == 2
    assert second_resolution.scene_batches[0].outcomes[0].success is True
    assert latest.current_turn == 3
    assert latest.pending_players == []


def test_scenario_service_replays_expected_turn() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "move", "target_scene_id": "storage"},
        },
    )

    first = asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))
    replay = asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))
    latest = service.get_party(created.session_id)

    assert first.model_dump() == replay.model_dump()
    assert latest.current_turn == 2
    assert service.list_resolved_turns(created.session_id) == [1]
    assert service.get_turn_resolution(created.session_id, 1).turn_no == 1


def test_scenario_service_submit_text_intent_accepts_clear_move() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    response = service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "我去储藏室"},
    )
    latest = service.get_party(created.session_id)

    assert response.accepted is True
    assert response.normalization.intent_payload == {
        "type": "move",
        "target_scene_id": "storage",
    }
    assert latest.pending_players == ["keeper"]


def test_scenario_service_submit_text_intent_accepts_observe() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party(
        {"module_id": "tokoyami_subset", "creator_id": "keeper"}
    )

    response = service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "我只是想确认一下什么情况"},
    )
    resolution = asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))
    latest = service.get_party(created.session_id)

    assert response.accepted is True
    assert response.normalization.intent_payload == {
        "type": "observe",
        "text": "我只是想确认一下什么情况",
    }
    assert response.normalization.matched_kind == "observe"
    assert resolution.scene_batches[0].outcomes[0].intent_type == "observe"
    assert resolution.scene_batches[0].outcomes[0].effects_applied == []
    assert latest.current_stage_id == "awake"
    assert latest.players[0].current_scene_id == "car_6"


def test_scenario_service_submit_text_intent_accepts_freeform_non_progression() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    response = service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "我开始跳舞"},
    )
    resolution = asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))
    latest = service.get_party(created.session_id)

    assert response.accepted is True
    assert response.normalization.intent_payload == {
        "type": "observe",
        "text": "我开始跳舞",
    }
    assert response.normalization.matched_id == "freeform"
    assert resolution.scene_batches[0].outcomes[0].intent_type == "observe"
    assert resolution.scene_batches[0].outcomes[0].effects_applied == []
    assert latest.players[0].current_scene_id == "foyer"


def test_scenario_service_submit_text_intent_preserves_deferred_observe() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party(
        {"module_id": "tokoyami_subset", "creator_id": "keeper"}
    )

    response = service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "去车厢尽头廊道仔细查看一下"},
    )
    resolution = asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))
    latest = service.get_party(created.session_id)

    assert response.accepted is True
    assert response.normalization.intent_payload == {
        "type": "move",
        "target_scene_id": "car_4",
    }
    assert response.normalization.deferred_intents == [
        {
            "type": "observe",
            "text": "去车厢尽头廊道仔细查看一下",
            "after": "move",
            "reason": "移动后继续观察目标场景；本回合不会因此自动揭示未触发线索。",
            "confidence": 0.67,
        }
    ]
    assert "observe:deferred:0.67" in response.normalization.match_basis
    assert resolution.scene_batches[0].outcomes[0].intent_type == "move"
    assert latest.players[0].current_scene_id == "car_4"


def test_scenario_service_submit_text_intent_clarifies_unclear_input() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    response = service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "随便来点什么"},
    )
    latest = service.get_party(created.session_id)

    assert response.accepted is False
    assert response.normalization.intent_payload is None
    assert response.normalization.clarification_question
    assert latest.pending_players == []


def test_scenario_service_builds_player_and_keeper_session_views() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    service.join_party(created.session_id, {"player_id": "p2"})
    service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "move", "target_scene_id": "storage"},
        },
    )
    asyncio.run(service.resolve_turn(created.session_id))

    player_view = service.get_player_view(created.session_id, "keeper")
    keeper_view = service.get_keeper_view(created.session_id)

    assert player_view.player_id == "keeper"
    assert player_view.current_scene_id == "storage"
    assert {action.action_id for action in player_view.available_actions} >= {
        "find_key"
    }
    assert keeper_view.player_scene_ids == {"keeper": "storage", "p2": "foyer"}
    assert keeper_view.current_turn == 2


def test_scenario_service_enforces_view_requester_scope() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    service.join_party(created.session_id, {"player_id": "p2"})

    assert (
        service.get_player_view(
            created.session_id,
            "p2",
            requester_id="p2",
        ).player_id
        == "p2"
    )
    assert (
        service.get_player_view(
            created.session_id,
            "p2",
            requester_id="keeper",
        ).player_id
        == "p2"
    )
    assert service.get_keeper_view(
        created.session_id,
        requester_id="keeper",
    ).session_id == created.session_id

    with pytest.raises(PermissionError, match="无权查看玩家"):
        service.get_player_view(created.session_id, "keeper", requester_id="p2")
    with pytest.raises(PermissionError, match="无权查看守密人视图"):
        service.get_keeper_view(created.session_id, requester_id="p2")


def test_scenario_service_rejects_duplicate_intent_submission() -> None:
    service = ScenarioService()
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "move", "target_scene_id": "storage"},
        },
    )

    with pytest.raises(ValueError, match="已经提交过意图"):
        service.submit_intent(
            created.session_id,
            {
                "player_id": "keeper",
                "intent": {"type": "move", "target_scene_id": "control"},
            },
        )


def test_scenario_service_rejects_unknown_player_intent() -> None:
    service = ScenarioService()
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})

    with pytest.raises(KeyError, match="未知玩家"):
        service.submit_intent(
            created.session_id,
            {
                "player_id": "ghost",
                "intent": {"type": "move", "target_scene_id": "storage"},
            },
        )

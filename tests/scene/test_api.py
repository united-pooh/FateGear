from __future__ import annotations

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
    first_resolution = service.resolve_turn(created.session_id)
    service.submit_intent(
        created.session_id,
        {
            "player_id": "keeper",
            "intent": {"type": "action", "action_id": "find_key"},
        },
    )
    second_resolution = service.resolve_turn(created.session_id)
    latest = service.get_party(created.session_id)

    assert submitted.pending_players == ["keeper"]
    assert first_resolution.next_turn == 2
    assert second_resolution.turn_no == 2
    assert second_resolution.scene_batches[0].outcomes[0].success is True
    assert latest.current_turn == 3
    assert latest.pending_players == []


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

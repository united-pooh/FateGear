from __future__ import annotations

import pytest

from scenario.api import ScenarioService


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

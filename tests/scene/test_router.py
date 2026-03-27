from __future__ import annotations

import inspect

import pytest

from scene.router import SceneRouter


@pytest.mark.parametrize(
    ("method_name", "expected_parameters"),
    [
        ("can_move", ("session_id", "player_id", "target_scene_id")),
        ("move_player", ("session_id", "player_id", "target_scene_id")),
        ("move_group", ("session_id", "player_ids", "target_scene_id")),
        ("list_reachable_scenes", ("session_id", "player_id")),
        ("group_players_by_scene", ("session_id",)),
        ("get_scene_snapshot", ("session_id", "scene_id")),
        ("get_player_view", ("session_id", "player_id")),
    ],
)
def test_scene_router_public_api_matches_readme(
    method_name: str, expected_parameters: tuple[str, ...]
) -> None:
    router = SceneRouter()
    method = getattr(router, method_name)

    assert tuple(inspect.signature(method).parameters) == expected_parameters


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("can_move", ("session_1", "player_1", "car_2")),
        ("move_player", ("session_1", "player_1", "car_2")),
        ("move_group", ("session_1", ["player_1", "player_2"], "car_2")),
        ("list_reachable_scenes", ("session_1", "player_1")),
        ("group_players_by_scene", ("session_1",)),
        ("get_scene_snapshot", ("session_1", "car_2")),
        ("get_player_view", ("session_1", "player_1")),
    ],
)
def test_scene_router_methods_are_explicitly_unimplemented(
    method_name: str, args: tuple[object, ...]
) -> None:
    router = SceneRouter()
    method = getattr(router, method_name)

    with pytest.raises(NotImplementedError):
        method(*args)

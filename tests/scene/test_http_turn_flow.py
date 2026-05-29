from __future__ import annotations

import asyncio
import json

import main
from scenario.api import ScenarioService
from scenario.runtime import SceneRuntime


class _FakeRequest:
    def __init__(
        self,
        *,
        app,
        payload: dict[str, object] | None = None,
        match_info: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self._payload = payload
        self.match_info = match_info or {}

    @property
    def can_read_body(self) -> bool:
        return self._payload is not None

    async def json(self) -> dict[str, object]:
        if self._payload is None:
            raise AssertionError("json() should not be called without payload")
        return self._payload


def test_http_turn_flow_supports_submit_intent_and_resolve() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)

        create_response = await main.handle_create_session(
            _FakeRequest(
                app=app,
                payload={"module_id": "generic_mvp", "creator_id": "keeper"},
            )
        )
        created = json.loads(create_response.text)

        join_response = await main.handle_join_session(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                payload={"player_id": "p2"},
            )
        )
        joined = json.loads(join_response.text)

        submit_response = await main.handle_submit_intent(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                payload={
                    "player_id": "keeper",
                    "intent": {"type": "move", "target_scene_id": "storage"},
                },
            )
        )
        submitted = json.loads(submit_response.text)
        text_submit_response = await main.handle_submit_text_intent(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                payload={"player_id": "p2", "text": "我也想去储藏室"},
            )
        )
        text_submitted = json.loads(text_submit_response.text)

        resolve_response = await main.handle_resolve_turn(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
            )
        )
        resolved = json.loads(resolve_response.text)
        player_view_response = await main.handle_get_player_view(
            _FakeRequest(
                app=app,
                match_info={
                    "session_id": created["session_id"],
                    "player_id": "keeper",
                },
            )
        )
        player_view = json.loads(player_view_response.text)
        keeper_view_response = await main.handle_get_keeper_view(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
            )
        )
        keeper_view = json.loads(keeper_view_response.text)

        assert create_response.status == 201
        assert join_response.status == 200
        assert submit_response.status == 200
        assert text_submit_response.status == 200
        assert resolve_response.status == 200
        assert player_view_response.status == 200
        assert keeper_view_response.status == 200
        assert [player["player_id"] for player in joined["players"]] == ["keeper", "p2"]
        assert submitted["pending_players"] == ["keeper"]
        assert text_submitted["accepted"] is True
        assert text_submitted["normalization"]["intent_payload"] == {
            "type": "move",
            "target_scene_id": "storage",
        }
        assert resolved["turn_no"] == 1
        assert resolved["next_turn"] == 2
        assert all(scene["outcomes"][0]["success"] for scene in resolved["scenes"])
        assert resolved["event_log"][0]["type"] == "turn_started"
        assert player_view["player_id"] == "keeper"
        assert player_view["current_scene_id"] == "storage"
        assert keeper_view["player_scene_ids"]["keeper"] == "storage"

    asyncio.run(run())

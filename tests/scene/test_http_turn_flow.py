from __future__ import annotations

import asyncio
import json

import main
import pytest
from scenario.api import ScenarioService
from scenario.runtime import SceneRuntime


class _FakeRequest:
    def __init__(
        self,
        *,
        app,
        payload: dict[str, object] | None = None,
        match_info: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self._payload = payload
        self.match_info = match_info or {}
        self.query = query or {}
        self.headers = headers or {}

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
        keeper_headers = {
            "Authorization": f"Bearer dev:keeper:keeper:{created['session_id']}:-"
        }

        resolve_response = await main.handle_resolve_turn(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                payload={"expected_turn": 1},
                headers=keeper_headers,
            )
        )
        resolved = json.loads(resolve_response.text)
        replay_response = await main.handle_resolve_turn(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                payload={"expected_turn": 1},
                headers=keeper_headers,
            )
        )
        replayed = json.loads(replay_response.text)
        player_view_response = await main.handle_get_player_view(
            _FakeRequest(
                app=app,
                match_info={
                    "session_id": created["session_id"],
                    "player_id": "keeper",
                },
                headers=keeper_headers,
            )
        )
        player_view = json.loads(player_view_response.text)
        keeper_view_response = await main.handle_get_keeper_view(
            _FakeRequest(
                app=app,
                match_info={"session_id": created["session_id"]},
                headers=keeper_headers,
            )
        )
        keeper_view = json.loads(keeper_view_response.text)

        assert create_response.status == 201
        assert join_response.status == 200
        assert submit_response.status == 200
        assert text_submit_response.status == 200
        assert resolve_response.status == 200
        assert replay_response.status == 200
        assert player_view_response.status == 200
        assert keeper_view_response.status == 200
        assert [player["player_id"] for player in joined["players"]] == ["keeper", "p2"]
        assert submitted["pending_players"] == ["keeper"]
        assert text_submitted["accepted"] is False
        assert text_submitted["normalization"]["intent_payload"] is None
        assert text_submitted["normalization"]["match_basis"] == ["agent_required"]
        assert resolved["turn_no"] == 1
        assert resolved["next_turn"] == 2
        assert replayed["turn_no"] == 1
        assert replayed["next_turn"] == 2
        assert resolved == replayed
        assert all(scene["outcomes"][0]["success"] for scene in resolved["scenes"])
        assert resolved["event_log"][0]["type"] == "turn_started"
        assert player_view["player_id"] == "keeper"
        assert player_view["current_scene_id"] == "storage"
        assert keeper_view["player_scene_ids"]["keeper"] == "storage"

    asyncio.run(run())


def test_http_create_session_enable_ktsl_returns_enabled_summary() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)

        create_response = await main.handle_create_session(
            _FakeRequest(
                app=app,
                payload={
                    "module_id": "generic_mvp",
                    "creator_id": "keeper",
                    "enable_ktsl": True,
                },
            )
        )
        created = json.loads(create_response.text)
        session = service._runtime.get_session(created["session_id"])

        assert create_response.status == 201
        assert created["ktsl_enabled"] is True
        assert session.ktsl_ledger is not None

    asyncio.run(run())


def test_http_view_handlers_reject_wrong_requester_scope() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)
        created = service.create_party(
            {"module_id": "generic_mvp", "creator_id": "keeper"}
        )
        service.join_party(created.session_id, {"player_id": "p2"})

        with pytest.raises(PermissionError, match="无权查看守密人视图"):
            await main.handle_get_keeper_view(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": created.session_id},
                    headers={
                        "Authorization": (
                            f"Bearer dev:player:p2:{created.session_id}:p2"
                        )
                    },
                )
            )
        with pytest.raises(PermissionError, match="无权查看玩家"):
            await main.handle_get_player_view(
                _FakeRequest(
                    app=app,
                    match_info={
                        "session_id": created.session_id,
                        "player_id": "keeper",
                    },
                    headers={
                        "Authorization": (
                            f"Bearer dev:player:p2:{created.session_id}:p2"
                        )
                    },
                )
            )

    asyncio.run(run())

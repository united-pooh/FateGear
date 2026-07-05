from __future__ import annotations

import asyncio
import json

import main
import pytest
from scenario.api import ScenarioService
from scenario.auth import (
    AuthenticationRequired,
    AuthorizationDenied,
    PERMISSION_VIEW_KEEPER,
    Principal,
    authorize_keeper_view,
    authorize_player_view,
    authorize_public_view,
    ensure_service_task_access,
    parse_authorization_header,
    parse_dev_token,
)
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


def test_parse_authorization_header_accepts_dev_bearer_token() -> None:
    principal = parse_authorization_header(
        "Bearer dev:player:p2:session-1:p2"
    )

    assert principal == Principal(
        principal_id="p2",
        role="player",
        session_id="session-1",
        player_id="p2",
    )


def test_missing_authorization_header_is_401ish_error() -> None:
    with pytest.raises(AuthenticationRequired) as exc_info:
        parse_authorization_header(None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == "authentication_required"


def test_principal_view_authorization_matrix() -> None:
    session_id = "session-1"
    player = Principal(
        principal_id="p1",
        role="player",
        session_id=session_id,
        player_id="p1",
    )
    keeper = Principal(
        principal_id="keeper",
        role="keeper",
        session_id=session_id,
    )
    observer = Principal(
        principal_id="observer",
        role="observer",
        session_id=session_id,
    )

    authorize_player_view(
        player,
        session_id=session_id,
        target_player_id="p1",
    )
    authorize_keeper_view(keeper, session_id=session_id)
    authorize_public_view(observer, session_id=session_id)

    with pytest.raises(AuthorizationDenied, match="无权查看玩家"):
        authorize_player_view(
            player,
            session_id=session_id,
            target_player_id="p2",
        )
    with pytest.raises(AuthorizationDenied, match="无权查看守密人视图"):
        authorize_keeper_view(player, session_id=session_id)
    with pytest.raises(AuthorizationDenied, match="无权查看玩家"):
        authorize_player_view(
            observer,
            session_id=session_id,
            target_player_id="p1",
        )
    with pytest.raises(AuthorizationDenied, match="无权查看守密人视图"):
        authorize_keeper_view(observer, session_id=session_id)
    with pytest.raises(AuthorizationDenied, match="无权访问会话 session-2"):
        authorize_public_view(observer, session_id="session-2")

    denied = AuthorizationDenied("nope")
    assert denied.status_code == 403


def test_service_dev_token_can_be_used_for_offline_tasks() -> None:
    service = parse_dev_token("dev:service:offline-worker:-:-")

    ensure_service_task_access(service)
    authorize_keeper_view(service, session_id="session-1")


def test_service_principal_can_be_granted_explicit_keeper_view_permission() -> None:
    service = Principal(
        principal_id="offline-worker",
        role="service",
        permissions=frozenset({PERMISSION_VIEW_KEEPER}),
    )

    authorize_keeper_view(service, session_id="session-1")


def test_scenario_service_accepts_principal_and_preserves_requester_id_compat() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    service.join_party(created.session_id, {"player_id": "p2"})

    player = Principal(
        principal_id="p2",
        role="player",
        session_id=created.session_id,
        player_id="p2",
    )
    keeper = Principal(
        principal_id="keeper",
        role="keeper",
        session_id=created.session_id,
    )

    assert (
        service.get_player_view(
            created.session_id,
            "p2",
            principal=player,
        ).player_id
        == "p2"
    )
    assert (
        service.get_keeper_view(
            created.session_id,
            requester_id="keeper",
        ).session_id
        == created.session_id
    )
    assert service.get_keeper_view(created.session_id).session_id == created.session_id
    assert (
        service.get_keeper_view(
            created.session_id,
            principal=keeper,
        ).session_id
        == created.session_id
    )

    with pytest.raises(AuthorizationDenied, match="无权查看玩家"):
        service.get_player_view(created.session_id, "keeper", principal=player)
    with pytest.raises(AuthorizationDenied, match="无权查看守密人视图"):
        service.get_keeper_view(created.session_id, principal=player)


def test_http_player_view_handler_reads_authorization_bearer_principal() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)
        created = service.create_party(
            {"module_id": "generic_mvp", "creator_id": "keeper"}
        )
        service.join_party(created.session_id, {"player_id": "p2"})

        response = await main.handle_get_player_view(
            _FakeRequest(
                app=app,
                match_info={
                    "session_id": created.session_id,
                    "player_id": "p2",
                },
                headers={
                    "Authorization": (
                        f"Bearer dev:player:p2:{created.session_id}:p2"
                    )
                },
            )
        )
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload["player_id"] == "p2"

    asyncio.run(run())


def test_http_view_handlers_require_authorization_and_scope_roles() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)
        created = service.create_party(
            {"module_id": "generic_mvp", "creator_id": "keeper"}
        )
        service.join_party(created.session_id, {"player_id": "p2"})

        missing = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={
                    "session_id": created.session_id,
                    "player_id": "p2",
                },
            ),
            main.handle_get_player_view,
        )
        wrong_role = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={"session_id": created.session_id},
                headers={
                    "Authorization": (
                        f"Bearer dev:observer:obs:{created.session_id}:-"
                    )
                },
            ),
            main.handle_get_keeper_view,
        )
        wrong_player = await main.error_middleware(
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
            ),
            main.handle_get_player_view,
        )

        assert missing.status == 401
        assert wrong_role.status == 403
        assert wrong_player.status == 403

    asyncio.run(run())


def test_http_keeper_and_service_tokens_can_view_and_resolve() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)
        created = service.create_party(
            {"module_id": "generic_mvp", "creator_id": "keeper"}
        )

        keeper_view = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={"session_id": created.session_id},
                headers={
                    "Authorization": (
                        f"Bearer dev:keeper:keeper:{created.session_id}:-"
                    )
                },
            ),
            main.handle_get_keeper_view,
        )
        service_view = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={"session_id": created.session_id},
                headers={
                    "Authorization": (
                        f"Bearer dev:service:svc:{created.session_id}:-"
                    )
                },
            ),
            main.handle_get_keeper_view,
        )
        resolved = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={"session_id": created.session_id},
                payload={"expected_turn": 1},
                headers={
                    "Authorization": (
                        f"Bearer dev:service:svc:{created.session_id}:-"
                    )
                },
            ),
            main.handle_resolve_turn,
        )

        assert keeper_view.status == 200
        assert service_view.status == 200
        assert resolved.status == 200

    asyncio.run(run())


def test_http_resolve_requires_auth_before_turn_side_effects() -> None:
    async def run() -> None:
        service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))
        app = main.create_app(service)
        created = service.create_party(
            {"module_id": "generic_mvp", "creator_id": "keeper"}
        )
        service.submit_intent(
            created.session_id,
            {
                "player_id": "keeper",
                "intent": {"type": "move", "target_scene_id": "storage"},
            },
        )

        before = service.get_party(created.session_id)
        response = await main.error_middleware(
            _FakeRequest(
                app=app,
                match_info={"session_id": created.session_id},
                payload={"expected_turn": 1},
            ),
            main.handle_resolve_turn,
        )
        after = service.get_party(created.session_id)

        assert response.status == 401
        assert after.current_turn == before.current_turn
        assert after.pending_players == before.pending_players
        assert service.list_resolved_turns(created.session_id) == []

    asyncio.run(run())

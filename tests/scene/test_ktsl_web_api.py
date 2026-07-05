"""Tests for the KTSL REST API (Phase 6 — ``ktsl_router.py``).

Uses the lightweight ``_FakeRequest`` pattern already established in
``test_http_turn_flow.py`` — no network, no real aiohttp client.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import KTSLFixture, SessionConfig
from scenario.session_audit_tracker import SessionAuditTracker
from scenario.web.ktsl_router import (
    _SESSION_STORE,
    create_ktsl_app,
    handle_create_session,
    handle_destroy_session,
    handle_get_knowledge,
    handle_get_report,
    handle_get_state,
    handle_get_timeline,
    handle_publish,
    handle_replay,
    handle_submit_event,
    handle_validate,
)


# ---------------------------------------------------------------------------
# Lightweight fake request (mirrors test_http_turn_flow.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_app():
    """Return a clean ktsl app with an empty session store."""
    # Clear the module-level store to avoid cross-test pollution
    _SESSION_STORE.clear()
    return create_ktsl_app()


@pytest.fixture
def fixture() -> KTSLFixture:
    return build_library_sewer_church_fixture()


def _make_tracker(fixture: KTSLFixture, session_id: str = "test-session") -> SessionAuditTracker:
    config = SessionConfig(session_id=session_id, fixture_id=fixture.id)
    return SessionAuditTracker(fixture, config=config)


def _keeper_headers(session_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:keeper:keeper:{session_id}:-"}


def _service_headers(session_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:service:svc:{session_id}:-"}


def _player_headers(session_id: str, player_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:player:{player_id}:{session_id}:{player_id}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    def test_validate_endpoint_returns_200(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_validate(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert body["valid"] is True
            assert body["error_count"] == 0

        asyncio.run(run())

    def test_validate_rejects_invalid_fixture(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            # Construct a minimal malformed fixture inline (bad JSON will fail,
            # but we use fixture_id that doesn't exist instead)
            resp = await handle_validate(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "nonexistent_fixture"},
                )
            )
            assert resp.status == 400
            body = json.loads(resp.text)
            assert "error" in body

        asyncio.run(run())

    def test_validate_rejects_unknown_fixture(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_validate(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "does_not_exist"},
                )
            )
            assert resp.status == 400
            body = json.loads(resp.text)
            assert body.get("error") == "unknown fixture"

        asyncio.run(run())


class TestCreateSessionReturns201:
    def test_create_session_returns_201(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            assert resp.status == 201
            body = json.loads(resp.text)
            assert "session_id" in body
            assert body["fixture_id"] == "library_sewer_church"
            assert body["fixture_title"] == "Library / Sewer / Church simulated fixture"
            # Session should be stored
            assert body["session_id"] in _SESSION_STORE

        asyncio.run(run())


class TestSubmitEventReturnsAuditResult:
    def test_submit_event_returns_audit_result(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            # Create session first
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            # Submit valid event
            resp = await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    payload={
                        "action": "investigate restricted archive index",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "allowed" in body
            assert body["allowed"] is True
            assert "resolution" in body
            assert "violations" in body
            assert "updated_metrics" in body

        asyncio.run(run())

    def test_submit_event_unknown_session_returns_404(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "no-such-session"},
                    payload={
                        "action": "do something",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )
            assert resp.status == 404
            body = json.loads(resp.text)
            assert body["error"] == "session not found"

        asyncio.run(run())


class TestGetStateReturnsMetrics:
    def test_get_state_returns_metrics(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_state(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "metrics" in body
            assert "barriers" in body
            assert "couplings" in body
            assert "event_count" in body
            assert isinstance(body["barriers"], list)
            assert isinstance(body["couplings"], list)

        asyncio.run(run())

    def test_get_state_unknown_session_returns_404(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_get_state(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "nonexistent"},
                    headers=_keeper_headers("nonexistent"),
                )
            )
            assert resp.status == 404

        asyncio.run(run())


class TestGetTimelineFiltersByScene:
    def test_get_timeline_filters_by_scene(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            # Submit a library event
            await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    payload={
                        "action": "investigate restricted archive index",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )

            # Get timeline for specific scene
            resp = await handle_get_timeline(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"scene_id": "scene_library"},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "scenes" in body
            assert "scene_library" in body["scenes"]
            # Sewer should not be in the filtered timeline
            assert "scene_sewer" not in body["scenes"]

        asyncio.run(run())

    def test_get_timeline_all_scenes_when_no_filter(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    payload={
                        "action": "investigate restricted archive index",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )

            resp = await handle_get_timeline(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "scene_library" in body["scenes"]

        asyncio.run(run())


class TestGetReport:
    def test_get_report_md(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    payload={
                        "action": "investigate restricted archive index",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )

            resp = await handle_get_report(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"format": "md"},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert body["format"] == "md"
            assert "content" in body
            assert "KTSL Session Report" in body["content"]
            assert body["fixture_id"] == "library_sewer_church"

        asyncio.run(run())

    def test_get_report_html(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_report(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"format": "html"},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            # html may fall back to md if jinja2 is not installed
            assert body["format"] in {"md", "html"}
            assert "content" in body

        asyncio.run(run())


class TestDestroySession:
    def test_destroy_session(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]
            assert session_id in _SESSION_STORE

            resp = await handle_destroy_session(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert body["destroyed"] is True
            assert body["session_id"] == session_id
            assert session_id not in _SESSION_STORE

        asyncio.run(run())

    def test_destroy_unknown_session_returns_404(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_destroy_session(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "no-such"},
                )
            )
            assert resp.status == 404

        asyncio.run(run())


class TestPublishReturnsResult:
    def test_publish_returns_result(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_publish(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "overall_pass" in body
            assert "per_mode" in body
            assert "fixture_id" in body
            assert "criteria_version" in body
            assert "evaluated_at" in body

        asyncio.run(run())

    def test_publish_with_explicit_criteria(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_publish(
                _FakeRequest(
                    app=app,
                    payload={
                        "fixture_id": "library_sewer_church",
                        "criteria": {
                            "version": "1.0.0",
                            "thresholds": {
                                "ktsl_full": {
                                    "max_causal_violations": 0,
                                    "max_unauthorized_actions": 0,
                                }
                            },
                        },
                    },
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "per_mode" in body

        asyncio.run(run())


class TestReplayReturnsReport:
    def test_replay_returns_report(self, tmp_path: Path) -> None:
        async def run() -> None:
            # Build a real session state file
            fixture = build_library_sewer_church_fixture()
            tracker = SessionAuditTracker(fixture)
            tracker.submit_action(
                action_text="investigate restricted archive index",
                actor="ada",
                scene_id="scene_library",
            )
            state_path = tmp_path / "session-state.json"
            tracker.save_state(state_path)

            app = _fresh_app()
            resp = await handle_replay(
                _FakeRequest(
                    app=app,
                    payload={"state_json": str(state_path)},
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "content" in body
            assert "format" in body
            assert "KTSL Session Report" in body["content"]

        asyncio.run(run())

    def test_replay_missing_file_returns_400(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_replay(
                _FakeRequest(
                    app=app,
                    payload={"state_json": "/nonexistent/path.json"},
                )
            )
            assert resp.status == 400
            body = json.loads(resp.text)
            assert "error" in body

        asyncio.run(run())

    def test_replay_missing_state_path_returns_400(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_replay(
                _FakeRequest(
                    app=app,
                    payload={},
                )
            )
            assert resp.status == 400

        asyncio.run(run())


class TestGetKnowledge:
    def test_get_knowledge_all_characters(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            await handle_submit_event(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    payload={
                        "action": "investigate restricted archive index",
                        "actor": "ada",
                        "scene_id": "scene_library",
                    },
                )
            )

            resp = await handle_get_knowledge(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_keeper_headers(session_id),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "knowledge_map" in body
            # ada should have gained knowledge from the event
            assert "ada" in body["knowledge_map"]

        asyncio.run(run())

    def test_get_knowledge_specific_character(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_knowledge(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"character_id": "ada"},
                    headers=_player_headers(session_id, "ada"),
                )
            )
            assert resp.status == 200
            body = json.loads(resp.text)
            assert "knowledge_map" in body

        asyncio.run(run())


class TestProtectedEndpointAuth:
    def test_protected_state_requires_token(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_state(
                _FakeRequest(app=app, match_info={"session_id": session_id})
            )
            body = json.loads(resp.text)

            assert resp.status == 401
            assert body["code"] == "authentication_required"

        asyncio.run(run())

    def test_protected_keeper_endpoints_reject_player_role(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_report(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_player_headers(session_id, "ada"),
                )
            )

            assert resp.status == 403

        asyncio.run(run())

    def test_knowledge_rejects_wrong_player_token(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            resp = await handle_get_knowledge(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"character_id": "ada"},
                    headers=_player_headers(session_id, "bruno"),
                )
            )

            assert resp.status == 403

        asyncio.run(run())

    def test_service_token_can_read_keeper_ktsl_surfaces(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            create_resp = await handle_create_session(
                _FakeRequest(
                    app=app,
                    payload={"fixture_id": "library_sewer_church"},
                )
            )
            session_id = json.loads(create_resp.text)["session_id"]

            state = await handle_get_state(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_service_headers(session_id),
                )
            )
            timeline = await handle_get_timeline(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_service_headers(session_id),
                )
            )
            report = await handle_get_report(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    headers=_service_headers(session_id),
                )
            )
            knowledge = await handle_get_knowledge(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": session_id},
                    query={"character_id": "ada"},
                    headers=_service_headers(session_id),
                )
            )

            assert state.status == 200
            assert timeline.status == 200
            assert report.status == 200
            assert knowledge.status == 200

        asyncio.run(run())


class TestSessionNotFound:
    """Verify 404 for all endpoints when session doesn't exist."""

    def test_get_timeline_unknown_session(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_get_timeline(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "ghost"},
                    headers=_keeper_headers("ghost"),
                )
            )
            assert resp.status == 404

        asyncio.run(run())

    def test_get_report_unknown_session(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_get_report(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "ghost"},
                    headers=_keeper_headers("ghost"),
                )
            )
            assert resp.status == 404

        asyncio.run(run())

    def test_get_knowledge_unknown_session(self) -> None:
        async def run() -> None:
            app = _fresh_app()
            resp = await handle_get_knowledge(
                _FakeRequest(
                    app=app,
                    match_info={"session_id": "ghost"},
                    headers=_keeper_headers("ghost"),
                )
            )
            assert resp.status == 404

        asyncio.run(run())

from __future__ import annotations

import asyncio
import json

from aiohttp.test_utils import make_mocked_request

import main
from scenario.api import ScenarioService


def test_create_app_registers_expected_routes_and_health_handler() -> None:
    async def run() -> None:
        app = main.create_app(ScenarioService())
        request = make_mocked_request("GET", "/health", app=app)

        response = await main.handle_health(request)
        registered_routes = {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
            if route.method != "HEAD"
        }

        assert response.status == 200
        assert json.loads(response.text) == {"status": "ok"}
        assert ("GET", "/health") in registered_routes
        assert ("GET", "/modules") in registered_routes
        assert ("GET", "/sessions") in registered_routes
        assert ("POST", "/sessions") in registered_routes
        assert ("GET", "/sessions/{session_id}") in registered_routes
        assert ("POST", "/sessions/{session_id}/players") in registered_routes
        assert ("POST", "/sessions/{session_id}/intents") in registered_routes
        assert ("POST", "/sessions/{session_id}/resolve") in registered_routes

    asyncio.run(run())

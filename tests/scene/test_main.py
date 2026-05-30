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


def test_build_service_enables_deepseek_agents_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.delenv("AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("PLANNER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("NARRATOR_AGENT_MODEL", raising=False)

    service = main.build_service(module_root=main.ROOT / "module")

    runtime = service._runtime
    assert runtime._plan_agent is not None
    assert runtime._render_agent is not None
    assert runtime._plan_agent.model_id == "deepseek-v4-pro"
    assert runtime._render_agent.model_id == "deepseek-v4-pro"


def test_build_service_can_disable_agents(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    service = main.build_service(
        module_root=main.ROOT / "module",
        enable_agents=False,
    )

    runtime = service._runtime
    assert runtime._plan_agent is None
    assert runtime._render_agent is None

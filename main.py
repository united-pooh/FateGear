from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aiohttp import ContentTypeError, web
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scenario.api import (  # noqa: E402
    CreatePartyRequest,
    JoinPartyRequest,
    ScenarioService,
    SubmitIntentRequest,
)

APP_SERVICE_KEY = web.AppKey("scenario_service", ScenarioService)


@web.middleware
async def error_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    try:
        return await handler(request)
    except ValidationError as exc:
        return web.json_response(
            {
                "error": "请求参数校验失败",
                "details": exc.errors(),
            },
            status=400,
        )
    except KeyError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except json.JSONDecodeError as exc:
        return web.json_response(
            {"error": f"请求体不是合法 JSON: {exc}"},
            status=400,
        )
    except ContentTypeError as exc:
        return web.json_response(
            {"error": f"请求体不是合法 JSON: {exc}"},
            status=400,
        )


def _service(request: web.Request) -> ScenarioService:
    return request.app[APP_SERVICE_KEY]


async def _read_json_body(request: web.Request) -> dict[str, object]:
    if not request.can_read_body:
        return {}

    payload = await request.json()
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return payload


async def handle_root(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "service": "FateGear",
            "endpoints": {
                "health": "GET /health",
                "modules": "GET /modules",
                "list_parties": "GET /sessions",
                "create_party": "POST /sessions",
                "get_party": "GET /sessions/{session_id}",
                "player_view": "GET /sessions/{session_id}/players/{player_id}/view",
                "keeper_view": "GET /sessions/{session_id}/keeper-view",
                "join_party": "POST /sessions/{session_id}/players",
                "submit_intent": "POST /sessions/{session_id}/intents",
                "resolve_turn": "POST /sessions/{session_id}/resolve (keeper view)",
            },
        }
    )


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_modules(request: web.Request) -> web.Response:
    modules = [module.model_dump() for module in _service(request).list_modules()]
    return web.json_response({"modules": modules})


async def handle_list_sessions(request: web.Request) -> web.Response:
    sessions = [party.model_dump() for party in _service(request).list_parties()]
    return web.json_response({"sessions": sessions})


async def handle_get_session(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    party = _service(request).get_party(session_id)
    return web.json_response(party.model_dump())


async def handle_get_player_view(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    player_id = request.match_info["player_id"]
    view = _service(request).get_player_view(session_id, player_id)
    return web.json_response(view.model_dump())


async def handle_get_keeper_view(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    view = _service(request).get_keeper_view(session_id)
    return web.json_response(view.model_dump())


async def handle_create_session(request: web.Request) -> web.Response:
    payload = CreatePartyRequest.model_validate(await _read_json_body(request))
    party = _service(request).create_party(payload)
    return web.json_response(party.model_dump(), status=201)


async def handle_join_session(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    payload = JoinPartyRequest.model_validate(await _read_json_body(request))
    party = _service(request).join_party(session_id, payload)
    return web.json_response(party.model_dump())


async def handle_submit_intent(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    payload = SubmitIntentRequest.model_validate(await _read_json_body(request))
    party = _service(request).submit_intent(session_id, payload)
    return web.json_response(party.model_dump())


async def handle_resolve_turn(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    resolution = await _service(request).resolve_turn(session_id)
    view = _service(request).build_keeper_turn_view(resolution=resolution)
    return web.json_response(view.model_dump())


def create_app(service: ScenarioService) -> web.Application:
    app = web.Application(middlewares=[error_middleware])
    app[APP_SERVICE_KEY] = service
    app.add_routes(
        [
            web.get("/", handle_root),
            web.get("/health", handle_health),
            web.get("/modules", handle_modules),
            web.get("/sessions", handle_list_sessions),
            web.post("/sessions", handle_create_session),
            web.get("/sessions/{session_id}", handle_get_session),
            web.get(
                "/sessions/{session_id}/players/{player_id}/view",
                handle_get_player_view,
            ),
            web.get("/sessions/{session_id}/keeper-view", handle_get_keeper_view),
            web.post("/sessions/{session_id}/players", handle_join_session),
            web.post("/sessions/{session_id}/intents", handle_submit_intent),
            web.post("/sessions/{session_id}/resolve", handle_resolve_turn),
        ]
    )
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 FateGear aiohttp 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--module-root",
        default=str(ROOT / "module"),
        help="模组目录路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = ScenarioService(module_root=args.module_root)
    app = create_app(service)

    print(f"FateGear aiohttp server running on http://{args.host}:{args.port}")
    print("Create party: POST /sessions")
    print("Join party:   POST /sessions/{session_id}/players")
    print("Submit turn:  POST /sessions/{session_id}/intents")
    print("Resolve turn: POST /sessions/{session_id}/resolve")
    print("List modules: GET /modules")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

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

from scenario.agent import KeeperIntentAgent, KeeperPlanAgent, KeeperRenderAgent  # noqa: E402
from scenario.agent.config import detect_provider_kind, load_agent_settings  # noqa: E402
from scenario.api import (  # noqa: E402
    CreatePartyRequest,
    JoinPartyRequest,
    RawPlayerIntent,
    ScenarioService,
    SubmitIntentRequest,
)
from scenario.runtime import SceneRuntime  # noqa: E402

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
    except PermissionError as exc:
        return web.json_response({"error": str(exc)}, status=403)
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


def _query_param(request: web.Request, key: str) -> str | None:
    query = getattr(request, "query", {})
    value = query.get(key)
    return str(value) if value is not None else None


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
                "submit_text_intent": "POST /sessions/{session_id}/text-intents",
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
    view = _service(request).get_player_view(
        session_id,
        player_id,
        requester_id=_query_param(request, "requester_id"),
    )
    return web.json_response(view.model_dump())


async def handle_get_keeper_view(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    view = _service(request).get_keeper_view(
        session_id,
        requester_id=_query_param(request, "requester_id"),
    )
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


async def handle_submit_text_intent(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    payload = RawPlayerIntent.model_validate(await _read_json_body(request))
    response = await _service(request).submit_text_intent_async(session_id, payload)
    return web.json_response(response.model_dump())


async def handle_resolve_turn(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    payload = await _read_json_body(request)
    expected_turn = payload.get("expected_turn")
    if expected_turn is not None and not isinstance(expected_turn, int):
        raise ValueError("expected_turn 必须是整数")
    requester_id = payload.get("requester_id")
    if requester_id is not None and not isinstance(requester_id, str):
        raise ValueError("requester_id 必须是字符串")
    resolution = await _service(request).resolve_turn(
        session_id,
        expected_turn=expected_turn,
    )
    view = _service(request).build_keeper_turn_view(
        resolution=resolution,
        requester_id=requester_id,
    )
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
            web.post(
                "/sessions/{session_id}/text-intents",
                handle_submit_text_intent,
            ),
            web.post("/sessions/{session_id}/resolve", handle_resolve_turn),
        ]
    )
    return app


def build_service(
    *,
    module_root: str | Path,
    enable_agents: bool = True,
    kp_audit_log_path: str | Path | None = None,
) -> ScenarioService:
    """Create the scenario service and attach configured LLM agents when available."""

    if not enable_agents:
        return ScenarioService(
            module_root=module_root,
            kp_audit_log_path=kp_audit_log_path,
        )

    settings = load_agent_settings()
    has_agent_key = bool(
        settings.planner_provider.api_key or settings.narrator_provider.api_key
    )
    if not has_agent_key:
        return ScenarioService(
            module_root=module_root,
            kp_audit_log_path=kp_audit_log_path,
        )

    intent_agent = KeeperIntentAgent(config=settings)
    planner = KeeperPlanAgent(config=settings)
    narrator = KeeperRenderAgent(config=settings)
    runtime = SceneRuntime(
        module_root=module_root,
        plan_agent=planner,
        render_agent=narrator,
    )
    provider_kind = detect_provider_kind(client=settings.default_provider)
    print(
        "Agent provider enabled: "
        f"{provider_kind}; planner={planner.model_id}; narrator={narrator.model_id}; "
        f"intent={intent_agent.model_id}"
    )
    return ScenarioService(
        module_root=module_root,
        runtime=runtime,
        intent_agent=intent_agent,
        kp_audit_log_path=kp_audit_log_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 FateGear aiohttp 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--module-root",
        default=str(ROOT / "module"),
        help="模组目录路径",
    )
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="禁用 Plan/Render LLM Agent，强制使用离线规则模式",
    )
    parser.add_argument(
        "--kp-log-path",
        default=str(ROOT / "log" / "kp-flow.jsonl"),
        help="KP 视角 JSONL 审计日志路径",
    )
    parser.add_argument(
        "--no-kp-log",
        action="store_true",
        help="禁用 KP 视角 JSONL 审计日志",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = build_service(
        module_root=args.module_root,
        enable_agents=not args.no_agents,
        kp_audit_log_path=None if args.no_kp_log else args.kp_log_path,
    )
    app = create_app(service)

    print(f"FateGear aiohttp server running on http://{args.host}:{args.port}")
    print("Create party: POST /sessions")
    print("Join party:   POST /sessions/{session_id}/players")
    print("Submit turn:  POST /sessions/{session_id}/intents")
    print("Resolve turn: POST /sessions/{session_id}/resolve")
    print("List modules: GET /modules")
    if not args.no_kp_log:
        print(f"KP audit log: {args.kp_log_path}")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

"""Interactive terminal runner for scenario modules."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from scenario.agent import KeeperPlanAgent, KeeperRenderAgent
from scenario.agent.config import detect_provider_kind, load_agent_settings
from scenario.api import ScenarioService
from scenario.io import MODULE_ROOT
from scenario.runtime import SceneRuntime


ROOT = Path(__file__).resolve().parents[3]

_LOCATION_QUERIES = (
    "我在哪里",
    "我在哪",
    "我在哪儿",
    "这是哪里",
    "这里是哪",
    "这里是哪里",
    "现在在哪",
    "现在在哪里",
    "当前位置",
)
_HELP_QUERIES = (
    "?",
    "？",
    "??",
    "？？",
    "何意味",
    "什么意思",
    "啥意思",
    "什么含义",
    "看不懂",
    "我不懂",
    "help",
    "帮助",
)


def _build_service(
    *,
    module_root: Path,
    no_agents: bool,
    kp_log_path: Path | None,
) -> ScenarioService:
    if no_agents:
        return ScenarioService(module_root=module_root, kp_audit_log_path=kp_log_path)

    settings = load_agent_settings()
    has_agent_key = bool(
        settings.planner_provider.api_key or settings.narrator_provider.api_key
    )
    if not has_agent_key:
        return ScenarioService(module_root=module_root, kp_audit_log_path=kp_log_path)

    planner = KeeperPlanAgent(config=settings)
    narrator = KeeperRenderAgent(config=settings)
    runtime = SceneRuntime(
        module_root=module_root,
        plan_agent=planner,
        render_agent=narrator,
    )
    provider = detect_provider_kind(client=settings.default_provider)
    print(
        f"[agent] provider={provider} planner={planner.model_id} "
        f"narrator={narrator.model_id}"
    )
    return ScenarioService(
        module_root=module_root,
        runtime=runtime,
        kp_audit_log_path=kp_log_path,
    )


def _print_player_view(service: ScenarioService, session_id: str, player_id: str) -> None:
    view = service.get_player_view(
        session_id,
        player_id,
        requester_id=player_id,
    )
    print()
    print(f"[scene] {view.current_scene_name} ({view.current_scene_id})")
    if view.current_scene_description:
        print(view.current_scene_description)
    if view.reachable_scene_ids:
        print("[reachable] " + ", ".join(view.reachable_scene_ids))
    if view.available_actions:
        actions = [
            f"{action.action_id}:{action.name}" for action in view.available_actions
        ]
        print("[actions] " + ", ".join(actions))
    print(f"[stage] {view.current_stage_id} turn={view.current_turn}")
    if view.resolved_ending:
        print(f"[ending] {view.resolved_ending}")


def _normalize_table_talk(raw: str) -> str:
    return "".join(raw.strip().split()).lower()


def _is_location_query(raw: str) -> bool:
    normalized = _normalize_table_talk(raw)
    return any(term in normalized for term in _LOCATION_QUERIES)


def _is_help_query(raw: str) -> bool:
    normalized = _normalize_table_talk(raw)
    return normalized in _HELP_QUERIES or normalized.endswith("什么意思")


def _handle_table_talk(
    *,
    service: ScenarioService,
    session_id: str,
    player_id: str,
    raw: str,
) -> bool:
    if _is_location_query(raw):
        print("[table] 当前位置查询，不消耗回合。")
        _print_player_view(service, session_id, player_id)
        return True
    if _is_help_query(raw):
        print(
            "[table] 这是桌上提问，不消耗回合。你可以输入角色行动；"
            "如果只是确认状况，可以说“观察周围”或“我在哪里”。"
        )
        print(":view 查看当前位置；:keeper 切换 KP 提示显示；:quit 退出")
        return True
    return False


def _print_turn_view(
    service: ScenarioService,
    *,
    resolution,
    player_id: str,
    show_kp: bool,
) -> None:
    player_view = service.build_player_turn_view(
        resolution=resolution,
        player_id=player_id,
        requester_id=player_id,
    )
    for scene in player_view.scenes:
        print()
        print(f"===== Turn {player_view.turn_no} | {scene.scene_id} =====")
        if scene.public_narration:
            print(scene.public_narration)
        for dialogue in scene.npc_dialogues:
            speaker = dialogue.npc_name or dialogue.npc_id or "NPC"
            print(f"\n[{speaker}] {dialogue.dialogue}")
        for clue in scene.private_clues:
            print(f"\n[private clue] {clue.clue_text}")

    if show_kp:
        keeper_view = service.build_keeper_turn_view(
            resolution=resolution,
            requester_id=player_id,
        )
        for scene in keeper_view.scenes:
            if scene.keeper_hint:
                print(f"\n[keeper hint] {scene.keeper_hint}")
        calls = resolution.agent_calls
        if calls:
            summary = ", ".join(
                f"{call.stage}:{call.model_id}:fallback={call.fallback_used}"
                for call in calls
            )
            print(f"\n[agent calls] {summary}")

    print()
    print(
        f"[state] stage={resolution.current_stage_id} "
        f"ending={resolution.resolved_ending or '-'} next_turn={resolution.next_turn}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在终端交互运行 FateGear 模组")
    parser.add_argument("--module", default="tokoyami_subset", help="模组 ID")
    parser.add_argument("--player", default="player", help="玩家 ID")
    parser.add_argument(
        "--module-root",
        default=str(MODULE_ROOT),
        help="模组目录路径",
    )
    parser.add_argument(
        "--kp-log-path",
        default=str(ROOT / "log" / "kp-flow.jsonl"),
        help="KP JSONL 审计日志路径",
    )
    parser.add_argument("--no-kp-log", action="store_true", help="禁用 KP JSONL 日志")
    parser.add_argument("--no-agents", action="store_true", help="禁用 LLM Agent")
    parser.add_argument(
        "--show-kp",
        action="store_true",
        help="在终端显示 keeper_hint 和 Agent 调用摘要",
    )
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    module_root = Path(args.module_root)
    kp_log_path = None if args.no_kp_log else Path(args.kp_log_path)
    service = _build_service(
        module_root=module_root,
        no_agents=args.no_agents,
        kp_log_path=kp_log_path,
    )
    party = service.create_party(
        {"module_id": args.module, "creator_id": args.player}
    )
    session_id = party.session_id

    print(f"[session] {session_id}")
    if kp_log_path is not None:
        print(f"[kp log] {kp_log_path}")
    print("输入中文行动后回车。命令：:help, :view, :keeper, :quit")

    show_kp = bool(args.show_kp)
    _print_player_view(service, session_id, args.player)

    while True:
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[bye]")
            return

        if not raw:
            continue
        if raw in {":quit", ":q", "quit", "exit"}:
            print("[bye]")
            return
        if raw == ":help":
            print(":view 查看当前位置；:keeper 切换 KP 提示显示；:quit 退出")
            continue
        if raw == ":view":
            _print_player_view(service, session_id, args.player)
            continue
        if raw == ":keeper":
            show_kp = not show_kp
            print(f"[keeper view] {'on' if show_kp else 'off'}")
            continue
        if _handle_table_talk(
            service=service,
            session_id=session_id,
            player_id=args.player,
            raw=raw,
        ):
            continue

        response = service.submit_text_intent(
            session_id,
            {"player_id": args.player, "text": raw},
        )
        if not response.accepted:
            norm = response.normalization
            print(norm.clarification_question or "这个行动还不够明确。")
            if norm.candidates:
                print("[candidates] " + ", ".join(norm.candidates))
            continue

        print(
            f"[intent] {response.normalization.matched_kind}:"
            f"{response.normalization.matched_id}"
        )
        resolution = await service.resolve_turn(
            session_id,
            expected_turn=response.party.current_turn if response.party else None,
        )
        _print_turn_view(
            service,
            resolution=resolution,
            player_id=args.player,
            show_kp=show_kp,
        )
        if resolution.resolved_ending:
            print("[module ended]")
            return


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

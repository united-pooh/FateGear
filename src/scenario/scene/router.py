"""`SceneRouter` 服务占位模块。

这里将来负责玩家分组、场景切换、可达场景查询和玩家视图构建。
"""

from __future__ import annotations

from .rules import MovementDecision, SceneMovementRules


class SceneRouter:
    """`SceneRouter` 服务占位模块。

    这里将来负责玩家分组、场景切换、可达场景查询和玩家视图构建。
    """

    def __init__(self, movement_rules: SceneMovementRules | None = None):
        self._movement_rules = movement_rules or SceneMovementRules()

    def _load_current_scene_id(self, *, session_id: str, player_id: str) -> str:
        raise NotImplementedError(
            "需要接入 SessionPlayerState 存储后，才能读取玩家当前所在场景"
        )

    def can_move(
        self,
        session_id: str,
        player_id: str,
        target_scene_id: str,
    ) -> MovementDecision:
        """读取玩家当前位置并委托 `SceneMovementRules` 进行移动规则判定。"""

        current_scene_id = self._load_current_scene_id(
            session_id=session_id,
            player_id=player_id,
        )
        return self._movement_rules.evaluate_transition(
            from_scene_id=current_scene_id,
            to_scene_id=target_scene_id,
        )

    def move_player(
        self, session_id: str, player_id: str, target_scene_id: str
    ) -> None:
        """校验玩家移动，并在未来接入状态更新与事件写入。"""

        raise NotImplementedError("需要接入状态存储与事件日志后，才能真正执行玩家移动")

    def move_group(
        self,
        session_id: str,
        player_ids: list[str],
        target_scene_id: str,
    ) -> None:
        """批量移动一组玩家。"""

        raise NotImplementedError("需要接入玩家状态存储后，才能实现多人移动")

    def list_reachable_scenes(self, session_id: str, player_id: str) -> list[str]:
        """列出玩家当前场景可达的其他场景。"""

        raise NotImplementedError("需要接入地图链接与玩家状态后，才能查询可达场景")

    def group_players_by_scene(self, session_id: str) -> dict[str, list[str]]:
        """根据当前场景对玩家进行分组。"""

        raise NotImplementedError("需要接入会话玩家快照后，才能按场景分组")

    def get_scene_snapshot(self, session_id: str, scene_id: str) -> dict[str, object]:
        """获取指定场景的会话快照信息。"""

        raise NotImplementedError("需要接入会话场景状态后，才能读取场景快照")

    def get_player_view(self, session_id: str, player_id: str) -> dict[str, object]:
        """构建玩家当前可见视图。"""

        raise NotImplementedError("需要接入可见性状态后，才能构建玩家视图")

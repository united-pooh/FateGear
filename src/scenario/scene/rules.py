"""场景移动规则骨架。

这里将来只放置地图上的移动规则判定，例如相邻、单向、锁定和隐藏通路。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from pydantic import BaseModel, Field

from .models import SceneLink


class MovementDecision(BaseModel):
    """场景移动规则的最小判定结果。"""

    allowed: bool
    reason: str = Field(default="")


class SceneMovementRules:
    """地图移动规则入口。

    这里不负责写入事件日志、更新玩家视图或修改会话状态。
    """

    def __init__(
        self,
        *,
        scene_links: Iterable[SceneLink] | None = None,
        active_flags: Collection[str] | None = None,
        active_stage_id: str | None = None,
    ) -> None:
        self._scene_links = list(scene_links) if scene_links is not None else None
        self._active_flags = set(active_flags) if active_flags is not None else None
        self._active_stage_id = active_stage_id

    def evaluate_transition(
        self,
        *,
        from_scene_id: str,
        to_scene_id: str,
        scene_links: Iterable[SceneLink] | None = None,
        active_flags: Collection[str] | None = None,
        active_stage_id: str | None = None,
    ) -> MovementDecision:
        """判断两个场景之间的移动是否允许。

        判定顺序为：是否存在连线 -> 连线锁定 -> required_flags -> required_stages。
        """

        effective_links = (
            list(scene_links) if scene_links is not None else self._scene_links
        )
        effective_flags = (
            set(active_flags) if active_flags is not None else self._active_flags
        )
        effective_stage_id = (
            active_stage_id if active_stage_id is not None else self._active_stage_id
        )

        if effective_links is None:
            raise NotImplementedError(
                "需要接入 Scene / SceneLink / SessionMapState 后，才能实现移动规则判定"
            )

        for link in effective_links:
            if link.from_scene_id != from_scene_id or link.to_scene_id != to_scene_id:
                continue

            # 锁定优先级最高，直接返回阻塞原因。
            if link.is_locked:
                return MovementDecision(
                    allowed=False,
                    reason=link.block_reason or "通路当前处于锁定状态",
                )

            current_flags = effective_flags or set()
            missing_flags = [
                flag for flag in link.required_flags if flag not in current_flags
            ]
            if missing_flags:
                reason = (
                    link.block_reason or f"缺少状态标记: {', '.join(missing_flags)}"
                )
                return MovementDecision(allowed=False, reason=reason)

            if link.required_stages:
                if (
                    effective_stage_id is None
                    or effective_stage_id not in link.required_stages
                ):
                    reason = link.block_reason or "当前剧情阶段不允许通过该通路"
                    return MovementDecision(allowed=False, reason=reason)

            return MovementDecision(allowed=True)

        return MovementDecision(allowed=False, reason="场景之间不存在可通行连线")

    def list_reachable_scenes(
        self,
        *,
        from_scene_id: str,
        scene_links: Iterable[SceneLink] | None = None,
        active_flags: Collection[str] | None = None,
        active_stage_id: str | None = None,
    ) -> list[str]:
        """列出当前场景下可直达的场景。

        通过复用 `evaluate_transition` 保持单点判定逻辑。
        """

        effective_links = (
            list(scene_links) if scene_links is not None else self._scene_links
        )
        if effective_links is None:
            raise NotImplementedError(
                "需要接入 Scene / SceneLink / SessionMapState 后，才能实现移动规则判定"
            )

        reachable: list[str] = []
        for link in effective_links:
            if link.from_scene_id != from_scene_id:
                continue
            decision = self.evaluate_transition(
                from_scene_id=from_scene_id,
                to_scene_id=link.to_scene_id,
                scene_links=effective_links,
                active_flags=active_flags
                if active_flags is not None
                else self._active_flags,
                active_stage_id=active_stage_id
                if active_stage_id is not None
                else self._active_stage_id,
            )
            if decision.allowed:
                reachable.append(link.to_scene_id)
        return reachable

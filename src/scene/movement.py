"""场景移动规则骨架。

这里将来只放置地图上的移动规则判定，例如相邻、单向、锁定和隐藏通路。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MovementDecision(BaseModel):
    """场景移动规则的最小判定结果。"""

    allowed: bool
    reason: str = Field(default="")


class SceneMovementRules:
    """地图移动规则入口。

    这里不负责写入事件日志、更新玩家视图或修改会话状态。
    """

    def evaluate_transition(
        self,
        *,
        from_scene_id: str,
        to_scene_id: str,
    ) -> MovementDecision:
        """判断两个场景之间的移动是否允许。"""

        raise NotImplementedError(
            "需要接入 Scene / SceneLink / SessionMapState 后，才能实现移动规则判定"
        )

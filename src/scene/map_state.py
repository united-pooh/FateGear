"""会话地图状态占位模块。

这里将来承载 `SessionMapState`、`SessionPlayerState` 和 `SceneInstanceState`，用于保存一局游戏中的场景状态。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SceneInstanceState(BaseModel):
    scene_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前场景实例对应的静态场景 ID。",
    )
    is_cleared: bool = Field(
        default=False,
        description="该场景是否已经被会话流程判定为完成或清空。",
    )
    has_event_occurred: bool = Field(
        default=False,
        description="该场景的核心事件是否已经在当前会话中触发过。",
    )


class SessionMapState(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前地图状态所属的会话 ID。",
    )
    scene_instances: dict[str, SceneInstanceState] = Field(
        default_factory=dict,
        description="当前会话内各场景实例状态，key 通常为 scene_id。",
    )


class SessionPlayerState(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前玩家状态所属的会话 ID。",
    )
    player_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="玩家在当前会话中的唯一标识。",
    )
    current_scene_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="玩家当前所在场景的 scene_id。",
    )
    last_scene_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="玩家最近一次移动前所在场景的 scene_id。",
    )
    visibility_state: dict[str, bool] = Field(
        default_factory=dict,
        description="玩家当前可见性状态表，用于标记 NPC、线索、路径等对象是否可见。",
    )

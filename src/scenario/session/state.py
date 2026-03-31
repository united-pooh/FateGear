"""会话地图状态占位模块。

这里将来承载 `SessionMapState`、`SessionPlayerState` 和 `SceneInstanceState`，用于保存一局游戏中的场景状态。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cards.domain.card import InvestigatorCard

from ..story.models import StoryState


class SceneInstanceState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

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
    completed_action_ids: set[str] = Field(
        default_factory=set,
        description="当前场景内已成功执行过的动作 ID。",
    )
    local_flags: set[str] = Field(
        default_factory=set,
        description="当前场景实例持有的局部状态标记。",
    )


class SessionMapState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前地图状态所属的会话 ID。",
    )
    module_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前会话绑定的模组 ID。",
    )
    current_turn: int = Field(
        default=1,
        ge=1,
        description="当前会话的全局回合数。",
    )
    story_state: StoryState = Field(
        ...,
        description="当前会话的剧情主阶段状态。",
    )
    global_flags: set[str] = Field(
        default_factory=set,
        description="当前会话的全局状态标记集合。",
    )
    clock_values: dict[str, int] = Field(
        default_factory=dict,
        description="当前会话的全局时钟值。",
    )
    completed_actions: set[str] = Field(
        default_factory=set,
        description="当前会话中已完成的一次性动作集合。",
    )
    triggered_clock_events: set[str] = Field(
        default_factory=set,
        description="已经触发过的时钟阈值事件，格式通常为 clock_id:value。",
    )
    scene_instances: dict[str, SceneInstanceState] = Field(
        default_factory=dict,
        description="当前会话内各场景实例状态，key 通常为 scene_id。",
    )
    player_states: dict[str, "SessionPlayerState"] = Field(
        default_factory=dict,
        description="当前会话的玩家状态表，key 为 player_id。",
    )
    pending_intents: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description="当前回合内待结算的结构化玩家意图。",
    )
    resolved_ending: str | None = Field(
        default=None,
        description="当前会话若已进入结局，则记录结局 ID。",
    )


class SessionPlayerState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

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

    investigator: InvestigatorCard = Field(
        ...,
        description="玩家操控的调查员卡数据。",
    )

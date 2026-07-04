"""会话地图状态占位模块。

这里将来承载 `SessionMapState`、`SessionPlayerState` 和 `SceneInstanceState`，
用于保存一局游戏中的场景状态。
同时提供 ``NPCSessionState`` 及其 CoC 7e 派生属性（HP/MP/SAN/DB/Move）。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from cards.domain.card import InvestigatorCard

from ..story.models import StoryState

# KTSLLedger is needed at runtime for pydantic model_rebuild() to resolve the
# forward-ref field on SessionMapState.  The ktsl.models module does not import
# this module, so there is no circular-import risk.
from ..ktsl.models import KTSLLedger  # noqa: F401 — used by pydantic forward-ref resolution


# CoC 7e 简化版伤害加值(DB)表。
# 键 = STR+SIZ 合计值, 值 = 伤害加值。
# 官方 7e 表格覆盖 2-12+ → {-2,-1,0,1d4,1d6,2d6,3d6,4d6,5d6,6d6,7d6,8d6,9d6,10d6,11d6,12d6,13d6,15d6},
# 此处简化为固定整数表, 超出范围视为 0 (文档化简化)。
_COE_DB_TABLE: dict[int, int] = {
    2: -2, 3: -2, 4: -2,
    5: -1, 6: -1, 7: -1, 8: -1,
    9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0,
    15: 1, 16: 1, 17: 1,
    18: 2, 19: 2,
    20: 3, 21: 3,
    22: 4, 23: 4,
    24: 5, 25: 5,
    26: 6,
    27: 7,
    28: 8,
    29: 9,
    30: 10,
}


def _safe_int(value: object, default: int = 50) -> int:
    """安全地将任意值(int/str/float)转换为 int, 失败时返回 default。"""
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


class NPCSessionState(BaseModel):
    """单个 NPC 在当前会话中的持久状态。

    只记录跨回合需要持久化的七个字段；HP/MP/SAN/伤害加值/移动力等
    通过 ``@property`` 派生自 ``characteristics``，不在此处持久化。

    Per-request caching: 使用实例内部 ``_derived_cache`` dict 缓存已计算的派生属性。
    回合开始时应调用 ``reset_derived_cache()`` 清空缓存。
    """

    model_config = ConfigDict(validate_assignment=True)

    npc_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="NPC 在当前模组内的唯一 ID。",
    )
    module_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="NPC 所属的模组 ID。",
    )
    current_scene_id: str = Field(
        default="",
        max_length=30,
        description="NPC 当前所在的 scene_id；为空字符串表示尚未进入任意场景。",
    )
    visible_to_player_ids: set[str] = Field(
        default_factory=set,
        description="当前能看到该 NPC 的玩家 ID 集合。",
    )
    characteristics: dict[str, int] = Field(
        default_factory=dict,
        description="CoC 7e 八维特征 (STR/CON/SIZ/DEX/APP/INT/POW/EDU), 值域 0-100。",
    )
    skills: dict[str, int] = Field(
        default_factory=dict,
        description="当前会话中 NPC 已经公开过的技能及其检定值。",
    )
    last_updated_turn: int = Field(
        default=1,
        ge=1,
        description="最近一次更新该 NPC 状态的全局回合号。",
    )
    # Per-request cache for derived properties (not persisted).
    _derived_cache: dict[str, object] = {}

    def reset_derived_cache(self) -> None:
        """回合开始时清空派生属性缓存。"""
        self._derived_cache.clear()

    # --- CoC 7e 派生访问器 ---
    @property
    def derived_hp(self) -> int:
        """生命值 = ceil((CON+SIZ)/10)。"""
        cache = self._derived_cache
        if "hp" not in cache:
            con = _safe_int(self.characteristics.get("CON"), 50)
            siz = _safe_int(self.characteristics.get("SIZ"), 50)
            cache["hp"] = math.ceil((con + siz) / 10)
        return cache["hp"]  # type: ignore[return-value]

    @property
    def derived_mp(self) -> int:
        """魔力值 = floor(POW/5)。"""
        cache = self._derived_cache
        if "mp" not in cache:
            pow_ = _safe_int(self.characteristics.get("POW"), 50)
            cache["mp"] = math.floor(pow_ / 5)
        return cache["mp"]  # type: ignore[return-value]

    @property
    def derived_san(self) -> int:
        """理智值 = POW (理智起始值等于 POW)。"""
        cache = self._derived_cache
        if "san" not in cache:
            cache["san"] = _safe_int(self.characteristics.get("POW"), 50)
        return cache["san"]  # type: ignore[return-value]

    @property
    def derived_db(self) -> int:
        """伤害加值(DB) = 查 STR+SIZ 合计值表。超出表范围则返回 0。"""
        cache = self._derived_cache
        if "db" not in cache:
            str_ = _safe_int(self.characteristics.get("STR"), 50)
            siz = _safe_int(self.characteristics.get("SIZ"), 50)
            total = str_ + siz
            cache["db"] = _COE_DB_TABLE.get(total, 0)
        return cache["db"]  # type: ignore[return-value]

    @property
    def derived_move(self) -> int:
        """移动力, 人类基准 8。若 DEX<SIZ 则 7, 若 DEX>SIZ 或 SIZ>DEX 则 9。"""
        cache = self._derived_cache
        if "move" not in cache:
            dex = _safe_int(self.characteristics.get("DEX"), 50)
            siz = _safe_int(self.characteristics.get("SIZ"), 50)
            if dex < siz:
                cache["move"] = 7
            elif dex > siz:
                cache["move"] = 9
            else:
                cache["move"] = 8
        return cache["move"]  # type: ignore[return-value]


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


PenaltyTier = Literal[
    "none",
    "warning",
    "minor_penalty",
    "major_penalty",
    "severe_penalty",
]


class IllegalMoveRiskState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    illegal_value: int = Field(
        default=0,
        ge=0,
        description="玩家越界移动风险值；由运行时维护，不由叙事层写入。",
    )
    consecutive_count: int = Field(
        default=0,
        ge=0,
        description="连续回合触发越界移动的次数。",
    )
    total_count: int = Field(
        default=0,
        ge=0,
        description="当前会话内累计越界移动次数。",
    )
    recent_window_count: int = Field(
        default=0,
        ge=0,
        description="近期窗口内越界移动次数，用于防止间隔违规被完全洗白。",
    )
    last_violation_turn: int | None = Field(
        default=None,
        ge=1,
        description="最近一次越界移动发生的回合。",
    )
    last_penalty_tier: PenaltyTier = Field(
        default="none",
        description="最近一次风险更新后的惩罚等级。",
    )
    severe_triggered: bool = Field(
        default=False,
        description="当前会话内是否已经触发过严重越界惩罚。",
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
    npc_states: dict[str, NPCSessionState] = Field(
        default_factory=dict,
        description="当前会话内各 NPC 持久状态，key 为 npc_id。HP/MP/SAN/DB/Move 派生属性按需实时计算。",
    )
    npc_patch_queue: list[dict] = Field(
        default_factory=list,
        description="Queued NPC state patches awaiting resolve_turn consumption.",
    )

    # KTSL runtime ledger — None means this session does not use KTSL protocol
    ktsl_ledger: Optional["KTSLLedger"] = Field(
        default=None,
        description="KTSL 运行时账本；None 表示本场游戏不启用 KTSL 协议。",
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
    illegal_move_risk: IllegalMoveRiskState = Field(
        default_factory=IllegalMoveRiskState,
        description="玩家越界移动风险状态，由运行时跨回合维护。",
    )

    investigator: InvestigatorCard = Field(
        ...,
        description="玩家操控的调查员卡数据。",
    )


# Resolve forward refs for SessionMapState (KTSLLedger is a TYPE_CHECKING import).
SessionMapState.model_rebuild()

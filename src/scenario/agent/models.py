"""Agent 契约模型。

定义 Plan 阶段和 Render 阶段的输入 / 输出 schema，以及分层 prompt 结构。

设计约定：
- 所有"提议"模型（Proposed*）均不包含最终效果，只含 Agent 的意图；
  实际效果由 RuleEngine / TransitionValidator 执行和验证。
- 所有模型继承 pydantic BaseModel，确保可序列化为 JSON（用于日志落库）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 公共枚举
# ---------------------------------------------------------------------------


class VisibleScope(str, Enum):
    """叙事可见范围。"""

    PUBLIC = "public"  # 所有玩家可见
    KEEPER = "keeper"  # 仅守密人可见
    PLAYER = "player"  # 特定玩家私有（搭配 player_id 使用）


# ---------------------------------------------------------------------------
# Plan Prompt 分层结构（输入侧）
# ---------------------------------------------------------------------------


class SystemLayer(BaseModel):
    """永久层：系统规则与 COC 7e 核心规则摘要。

    此层内容在同一模组内不变，可缓存复用。
    """

    coc_version: str = Field(default="7e", description="规则书版本标识。")
    rule_summary: str = Field(
        default="",
        description="COC 7e 核心规则摘要（技能检定、对抗检定、成功等级等）。",
    )
    keeper_role_hint: str = Field(
        default="你是 Call of Cthulhu 桌游的守密人，负责裁定玩家行动并推进故事。",
        description="守密人角色提示。",
    )


class ModuleLayer(BaseModel):
    """模组层：世界观设定与当前剧情阶段描述。"""

    module_id: str = Field(..., description="模组唯一标识。")
    module_title: str = Field(default="", description="模组标题。")
    worldview_brief: str = Field(default="", description="世界观简介（300 字以内）。")
    current_stage_id: str = Field(..., description="当前剧情阶段 ID。")
    current_stage_description: str = Field(
        default="", description="当前剧情阶段的守密人描述文本。"
    )
    available_transition_ids: list[str] = Field(
        default_factory=list,
        description="当前可触发的剧情迁移 ID 列表（仅供 Agent 参考，不授权直接触发）。",
    )


class SpatialLayer(BaseModel):
    """空间层：当前场景的静态描述与动态状态。"""

    scene_id: str = Field(..., description="场景 ID。")
    scene_name: str = Field(default="", description="场景名称。")
    scene_description: str = Field(default="", description="场景描述文本。")
    present_player_ids: list[str] = Field(
        default_factory=list, description="当前在场的玩家 ID 列表。"
    )
    reachable_scene_ids: list[str] = Field(
        default_factory=list, description="从当前场景可直接到达的场景 ID 列表。"
    )
    available_action_ids: list[str] = Field(
        default_factory=list, description="当前场景可执行的动作 ID 列表。"
    )
    global_flags: list[str] = Field(
        default_factory=list,
        description="当前会话的全局 flag 列表（提供给 Agent 参考）。",
    )
    clock_values: dict[str, int] = Field(
        default_factory=dict, description="当前会话的时钟值快照。"
    )


class HistoryLayer(BaseModel):
    """历史层：最近 N 轮关键事件摘要。"""

    recent_events_summary: list[str] = Field(
        default_factory=list,
        description="最近 N 轮的关键事件摘要（一事件一行，降序排列）。",
    )
    max_events: int = Field(default=10, description="纳入上下文的最多事件条数。")


class KeeperPrivateLayer(BaseModel):
    """私有层：仅守密人可见的提示（可选）。"""

    hidden_notes: str = Field(
        default="",
        description="守密人的隐藏备注，不对玩家暴露。",
    )
    npc_hidden_states: dict[str, str] = Field(
        default_factory=dict,
        description="NPC 的隐藏状态描述，key 为 npc_id。",
    )


class PlayerIntentSummary(BaseModel):
    """单条玩家意图的语义化摘要，用于填充 prompt。"""

    player_id: str
    intent_type: str = Field(description="`move` 或 `action`。")
    # 移动意图
    target_scene_id: str = Field(default="")
    # 动作意图
    action_id: str = Field(default="")
    action_name: str = Field(default="")
    action_description: str = Field(default="")


class AgentPlanPrompt(BaseModel):
    """Plan 阶段 prompt 的完整结构。

    分层设计允许：
    - 永久层在同一模组内缓存；
    - 模组层按阶段缓存；
    - 空间层和历史层每轮刷新。
    """

    session_id: str
    turn_no: int
    scene_id: str

    # 分层内容
    system: SystemLayer = Field(default_factory=SystemLayer)
    module: ModuleLayer
    spatial: SpatialLayer
    history: HistoryLayer = Field(default_factory=HistoryLayer)
    keeper_private: KeeperPrivateLayer = Field(default_factory=KeeperPrivateLayer)

    # 本轮待结算的意图列表
    pending_intents: list[PlayerIntentSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Plan 阶段输出（KeeperAgentPlan）
# ---------------------------------------------------------------------------


class ProposedCheck(BaseModel):
    """Agent 提议的技能检定。

    ``skill_key`` 对应 COC 7e 技能名（与 InvestigatorSkill.SkillKey 一致）。
    RuleEngine 收到后执行实际掷骰，不使用 ``proposed_difficulty``。
    """

    player_id: str
    action_id: str
    skill_key: str = Field(description="建议检定的技能 key，例如 'spot_hidden'。")
    proposed_difficulty: str = Field(
        default="normal",
        description="Agent 建议的难度（仅参考）：normal / hard / extreme。",
    )
    rationale: str = Field(default="", description="Agent 提议此检定的理由。")


class ProposedEffect(BaseModel):
    """Agent 提议的状态效果（flag / clock 变更）。

    TransitionValidator 校验后才会生效。
    """

    effect_type: str = Field(
        description="`set_flag` / `remove_flag` / `advance_clock`。"
    )
    target_id: str = Field(description="flag 名或 clock_id。")
    value: int = Field(
        default=1, description="clock 增量（effect_type 为 advance_clock 时有效）。"
    )
    rationale: str = Field(default="", description="Agent 提议此效果的理由。")


class ProposedTransition(BaseModel):
    """Agent 提议触发的剧情迁移。"""

    transition_id: str
    rationale: str = Field(default="", description="Agent 提议迁移的理由。")


class KeeperAgentPlan(BaseModel):
    """Plan 阶段的输出：结构化提议，须经 RuleEngine 验证后才能生效。

    所有字段均为"提议"，不得直接写入 session state。
    """

    # 对本批次玩家意图的自然语言理解
    intent_summary: str = Field(
        default="", description="Agent 对本批次玩家意图的综合理解（守密人视角）。"
    )

    # 检定提议
    proposed_checks: list[ProposedCheck] = Field(
        default_factory=list,
        description="Agent 建议执行的技能检定列表，可为空。",
    )

    # 效果提议
    proposed_effects: list[ProposedEffect] = Field(
        default_factory=list,
        description="Agent 建议的 flag / clock 变更列表，可为空。",
    )

    # 剧情迁移提议（最多一条）
    proposed_transition: ProposedTransition | None = Field(
        default=None,
        description="Agent 建议触发的剧情迁移，null 表示不触发。",
    )

    # 守密人私有备注（不对玩家展示）
    keeper_notes: str = Field(
        default="",
        description="Agent 的守密人内部备注，用于审计与下轮 prompt 构建。",
    )


# ---------------------------------------------------------------------------
# Render 阶段输入
# ---------------------------------------------------------------------------


class CommitResult(BaseModel):
    """Render 阶段的输入：Plan 执行后已提交的状态变更摘要。

    此结构由 SceneRuntime 在 commit_turn() 后填充，
    传入 KeeperRenderAgent 作为叙事生成依据。
    """

    session_id: str
    turn_no: int
    scene_id: str

    # 已执行的检定结果
    resolved_checks: list[dict] = Field(
        default_factory=list,
        description="RuleEngine 执行后的检定结果列表（含掷骰结果、成功等级）。",
    )

    # 实际生效的效果
    applied_effects: list[str] = Field(
        default_factory=list,
        description="已生效的效果描述列表，例如 '设置标记:clue_found'。",
    )

    # 是否触发了剧情迁移
    applied_transition_id: str | None = Field(default=None)
    new_stage_id: str | None = Field(default=None)

    # 是否到达结局
    resolved_ending: str | None = Field(default=None)

    # 本轮运行时事件摘要（精简版）
    event_summary: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Render 阶段输出（KeeperNarration）
# ---------------------------------------------------------------------------


class NPCDialogue(BaseModel):
    """单个 NPC 的台词。"""

    npc_id: str
    npc_name: str = Field(default="")
    dialogue: str
    visible_scope: VisibleScope = Field(default=VisibleScope.PUBLIC)


class PrivateClue(BaseModel):
    """仅对特定玩家可见的私有线索。"""

    player_id: str
    clue_text: str
    # 可选：关联的场景或动作
    related_action_id: str = Field(default="")


class KeeperNarration(BaseModel):
    """Render 阶段的输出：多层次叙事文本。

    Render 阶段只读，不触发任何状态变更。
    若 LLM 不可用，子系统应退化为模板化文本填充此结构。
    """

    # 公共叙事：所有玩家可见的场景描述
    public_narration: str = Field(
        default="",
        description="守密人对本轮结果的公共叙述，所有玩家可见。",
    )

    # NPC 台词
    npc_dialogues: list[NPCDialogue] = Field(
        default_factory=list,
        description="本轮涉及的 NPC 台词列表。",
    )

    # 私有线索
    private_clues: list[PrivateClue] = Field(
        default_factory=list,
        description="仅对特定玩家分发的私有线索。",
    )

    # 守密人提示（不对玩家展示）
    keeper_hint: str = Field(
        default="",
        description="守密人对下一轮的内部提示与剧情走向建议。",
    )

    # 是否使用了降级模板（审计用）
    is_fallback: bool = Field(
        default=False,
        description="True 表示 LLM 不可用，使用了降级模板生成叙事。",
    )

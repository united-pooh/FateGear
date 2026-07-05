"""FateGear Agent 模块。

公共 API 导出：

- ``BaseAgent``：所有 Agent 的抽象基类，定义 call / _call_llm / _parse_output / _fallback 接口。
- ``AgentCallRecord``：单次调用的完整记录（prompt + output + meta），用于审计日志落库。
- ``AgentCallMeta``：调用元数据（model_id / token 用量 / 耗时 / 是否降级）。
- ``AgentError`` / ``AgentTimeoutError`` / ``AgentOutputError``：异常层级。

- ``AgentPlanPrompt``：Plan 阶段 prompt 的分层结构。
- ``KeeperAgentPlan``：Plan 阶段输出（结构化提议）。
- ``CommitResult``：Render 阶段输入（已提交的回合结果）。
- ``KeeperNarration``：Render 阶段输出（叙事文本）。

- ``PromptBuilder``：从会话快照构造 AgentPlanPrompt。
- ``KeeperIntentAgent``：自然语言意图裁定 Agent（OpenAI 后端，含降级）。
- ``KeeperPlanAgent``：Plan 阶段 Agent（模型端点适配层，含降级）。
- ``KeeperRenderAgent``：Render 阶段 Agent（模型端点适配层，含降级）。
"""

from .base import (
    AgentCallMeta,
    AgentCallRecord,
    AgentError,
    AgentOutputError,
    AgentTimeoutError,
    BaseAgent,
)
from .models import (
    AgentPlanPrompt,
    AuthorizedPrivateClue,
    CommitResult,
    HistoryLayer,
    IntentAgentDecision,
    IntentAgentPrompt,
    KeeperAgentPlan,
    KeeperNarration,
    KeeperPrivateLayer,
    ModuleLayer,
    NarrativeContextLayer,
    NPCDialogue,
    PlayerIntentSummary,
    PrivateClue,
    ProposedCheck,
    ProposedEffect,
    ProposedTransition,
    SpatialLayer,
    SystemLayer,
    VisibleScope,
)
from .model_client import (
    AnthropicModelClient,
    ModelClient,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    OpenAICompatibleModelClient,
)
from .intent_agent import KeeperIntentAgent
from .plan_agent import KeeperPlanAgent
from .prompt_builder import PromptBuilder
from .render_agent import KeeperRenderAgent

__all__ = [
    # 基类与基础类型
    "BaseAgent",
    "AgentCallMeta",
    "AgentCallRecord",
    "AgentError",
    "AgentTimeoutError",
    "AgentOutputError",
    # 契约模型
    "AgentPlanPrompt",
    "AuthorizedPrivateClue",
    "SystemLayer",
    "ModuleLayer",
    "NarrativeContextLayer",
    "SpatialLayer",
    "HistoryLayer",
    "KeeperPrivateLayer",
    "IntentAgentPrompt",
    "IntentAgentDecision",
    "PlayerIntentSummary",
    "KeeperAgentPlan",
    "ProposedCheck",
    "ProposedEffect",
    "ProposedTransition",
    "CommitResult",
    "KeeperNarration",
    "NPCDialogue",
    "PrivateClue",
    "VisibleScope",
    "ModelClient",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
    "OpenAICompatibleModelClient",
    "AnthropicModelClient",
    # 工具与实现
    "PromptBuilder",
    "KeeperIntentAgent",
    "KeeperPlanAgent",
    "KeeperRenderAgent",
]

"""Agent 统一基类。

设计原则：
1. BaseAgent 定义所有 Agent 必须实现的接口和生命周期钩子。
2. 所有 Agent 均不持有状态，调用方需将上下文显式传入。
3. Agent 只输出"提议"，不触发任何状态修改。
4. 内置重试、超时、降级三层保护机制。
5. 每次调用均返回 AgentCallRecord，包含原始输入输出和元数据，
   调用方负责将其持久化到 agent_plan_log / narration_log。
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 泛型类型变量：输入 Prompt 模型 / 输出结果模型
PromptT = TypeVar("PromptT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass
class AgentCallMeta:
    """单次 Agent 调用的元数据，用于日志落库和性能追踪。"""

    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempt: int = 1  # 第几次尝试（含重试）
    fallback_used: bool = False  # 是否使用了降级策略


@dataclass
class AgentCallRecord(Generic[PromptT, OutputT]):
    """单次 Agent 调用的完整记录，调用方持久化到审计日志。"""

    prompt: PromptT
    output: OutputT
    meta: AgentCallMeta = field(default_factory=AgentCallMeta)


class AgentError(Exception):
    """Agent 调用失败的统一异常。"""


class AgentTimeoutError(AgentError):
    """Agent 调用超时。"""


class AgentOutputError(AgentError):
    """Agent 输出格式或内容不符合预期。"""


class BaseAgent(ABC, Generic[PromptT, OutputT]):
    """所有 FateGear Agent 的抽象基类。

    子类需实现：
    - ``_call_llm(prompt)``：向 LLM 发起实际调用，返回原始输出。
    - ``_parse_output(raw)``：将 LLM 原始输出解析为强类型 OutputT 模型。
    - ``_fallback(prompt)``：LLM 不可用时的降级策略，返回 OutputT。

    可选覆盖：
    - ``_validate_output(output, prompt)``：对解析后的输出做业务层校验。
    - ``_on_call_start(prompt)`` / ``_on_call_end(record)``：钩子，用于日志或监控。

    Example::

        class MyAgent(BaseAgent[MyPrompt, MyOutput]):
            async def _call_llm(self, prompt: MyPrompt) -> str:
                return await openai_client.chat(...)

            def _parse_output(self, raw: str) -> MyOutput:
                return MyOutput.model_validate_json(raw)

            def _fallback(self, prompt: MyPrompt) -> MyOutput:
                return MyOutput(text="暂时无法响应，请稍后重试。")
    """

    # 子类可覆盖的配置项
    max_retries: int = 2  # 最大重试次数（不含首次调用）
    timeout_seconds: float = 30.0  # 单次调用超时（秒）
    retry_delay_seconds: float = 1.0  # 重试间隔基数（指数退避）

    def __init__(self, *, model_id: str = "") -> None:
        """
        Args:
            model_id: 后端模型标识，例如 "gpt-4o" / "claude-3-5-sonnet"。
                      空字符串表示未绑定，由子类或环境变量决定。
        """
        self._model_id = model_id
        self._last_usage: dict[str, int] = {}

    @property
    def model_id(self) -> str:
        return self._model_id

    # ------------------------------------------------------------------
    # 公开入口：唯一调用点
    # ------------------------------------------------------------------

    async def call(self, prompt: PromptT) -> AgentCallRecord[PromptT, OutputT]:
        """执行 Agent 调用，内置重试与降级保护。

        调用顺序：
        1. ``_on_call_start(prompt)``
        2. 最多 ``max_retries + 1`` 次尝试：
           a. ``_call_llm(prompt)``（带超时）
           b. ``_parse_output(raw)``
           c. ``_validate_output(output, prompt)``
        3. 若所有尝试均失败，调用 ``_fallback(prompt)``
        4. ``_on_call_end(record)``
        5. 返回 ``AgentCallRecord``

        Raises:
            AgentError: 若降级也失败。
        """
        await self._on_call_start(prompt)

        meta = AgentCallMeta(model_id=self._model_id)
        output: OutputT | None = None
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            meta.attempt = attempt
            t0 = time.monotonic()
            try:
                self._last_usage = {}
                raw = await asyncio.wait_for(
                    self._call_llm(prompt),
                    timeout=self.timeout_seconds,
                )
                output = self._parse_output(raw)
                self._validate_output(output, prompt)
                meta.input_tokens = int(self._last_usage.get("input_tokens", 0))
                meta.output_tokens = int(self._last_usage.get("output_tokens", 0))
                meta.latency_ms = int((time.monotonic() - t0) * 1000)
                break  # 成功，跳出重试循环
            except asyncio.TimeoutError:
                meta.latency_ms = int((time.monotonic() - t0) * 1000)
                last_error = AgentTimeoutError(
                    f"Agent 调用超时（{self.timeout_seconds}s），attempt={attempt}"
                )
                logger.warning("%s", last_error)
            except AgentOutputError as exc:
                last_error = exc
                logger.warning("Agent 输出解析失败，attempt=%d：%s", attempt, exc)
            except Exception as exc:
                last_error = exc
                logger.warning("Agent 调用异常，attempt=%d：%s", attempt, exc)

            if attempt <= self.max_retries:
                delay = self.retry_delay_seconds * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        if output is None:
            # 所有重试均失败，执行降级
            logger.warning(
                "Agent 所有重试均失败，启用降级策略。last_error=%s", last_error
            )
            try:
                output = self._fallback(prompt)
                meta.fallback_used = True
            except Exception as exc:
                raise AgentError(f"Agent 降级策略也失败：{exc}") from last_error

        record: AgentCallRecord[PromptT, OutputT] = AgentCallRecord(
            prompt=prompt,
            output=output,
            meta=meta,
        )
        await self._on_call_end(record)
        return record

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    @abstractmethod
    async def _call_llm(self, prompt: PromptT) -> Any:  # noqa: ANN401
        """向 LLM 发起实际调用。

        返回值类型由子类约定（通常是 str 或 dict），
        由 ``_parse_output`` 负责转换为强类型。

        不应在此处做重试——重试由基类负责。
        """

    @abstractmethod
    def _parse_output(self, raw: Any) -> OutputT:  # noqa: ANN401
        """将 LLM 原始输出解析为强类型 OutputT。

        Raises:
            AgentOutputError: 若解析失败。
        """

    @abstractmethod
    def _fallback(self, prompt: PromptT) -> OutputT:
        """LLM 不可用或解析失败时的降级输出。

        必须返回语义上合法的 OutputT 实例（通常为模板化文本）。
        不应在降级中再次调用 LLM。
        """

    # ------------------------------------------------------------------
    # 可选覆盖
    # ------------------------------------------------------------------

    def _validate_output(self, output: OutputT, prompt: PromptT) -> None:
        """对解析后的输出做业务层校验。

        默认不做任何校验。子类可覆盖以实现：
        - 检查 Agent 提议是否越权（如直接推进结局）
        - 检查输出字段是否完整
        - 检查输出内容是否与 prompt 中的约束一致

        Raises:
            AgentOutputError: 若校验失败。
        """

    async def _on_call_start(self, prompt: PromptT) -> None:
        """调用开始前的钩子，默认无操作。

        子类可在此处：
        - 打印调试日志
        - 上报指标
        - 检查限流
        """

    async def _on_call_end(self, record: AgentCallRecord[PromptT, OutputT]) -> None:
        """调用结束后的钩子，默认无操作。

        子类可在此处：
        - 将 record 持久化到审计日志
        - 上报 token 用量指标
        """

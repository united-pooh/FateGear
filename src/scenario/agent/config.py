"""Agent 配置读取。

本模块负责：
1. 从仓库根目录 `.env` 与进程环境变量读取 Agent 运行参数
2. 维护共享默认配置 `AGENT_*`
3. 允许 `PLANNER_AGENT_*` / `NARRATOR_AGENT_*` 对共享默认配置做单独覆盖

配置优先级分两层：
1. 来源优先级：进程环境变量 > `.env` 文件 > 代码默认值
2. Agent 配置优先级：单独 Agent 配置 > 共享 `AGENT_*` 配置
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


@dataclass(frozen=True)
class OpenAIProviderConfig:
    """单个 Agent 的 OpenAI 连接配置。

    字段留空表示“未显式配置”，调用方可继续走 fallback。
    """

    api_key: str = ""
    base_url: str = ""
    organization: str = ""
    project: str = ""


@dataclass(frozen=True)
class AgentModelConfig:
    """单个 Agent 的模型与采样配置。"""

    model: str
    temperature: float
    top_p: float
    top_k: int | None
    timeout_seconds: float


@dataclass(frozen=True)
class AgentSettings:
    """Agent 全量配置。

    `default_provider` 对应共享 `AGENT_*` 配置；
    `planner_provider` / `narrator_provider` 则是在共享配置基础上，
    应用各自 Agent 的单独覆盖后得到的最终连接参数。
    """

    default_provider: OpenAIProviderConfig
    planner_provider: OpenAIProviderConfig
    narrator_provider: OpenAIProviderConfig
    planner: AgentModelConfig
    narrator: AgentModelConfig


def _read_env_file(path: Path) -> dict[str, str]:
    """读取简单的 `.env` 键值对。

    这里只支持最小能力：
    - 跳过空行和注释
    - 按第一处 `=` 切分键值
    - 去掉包裹值的单引号/双引号
    """

    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _read_str(
    key: str,
    *,
    env_file_values: dict[str, str],
    default: str = "",
    aliases: tuple[str, ...] = (),
) -> str:
    """读取字符串配置。

    先查进程环境，再查 `.env` 文件，最后回退到 `default`。
    `aliases` 用于兼容历史变量名或第三方 SDK 约定变量名。
    空字符串视为“未配置”，会继续向下回退。
    """

    for candidate in (key, *aliases):
        value = os.environ.get(candidate)
        if value is not None and value != "":
            return value
    for candidate in (key, *aliases):
        value = env_file_values.get(candidate)
        if value is not None and value != "":
            return value
    return default


def _read_float(
    key: str,
    *,
    env_file_values: dict[str, str],
    default: float,
    aliases: tuple[str, ...] = (),
) -> float:
    """读取浮点配置，非法值回退到默认值。"""

    raw = _read_str(
        key,
        env_file_values=env_file_values,
        default=str(default),
        aliases=aliases,
    )
    try:
        return float(raw)
    except ValueError:
        logger.warning("Agent 配置 %s=%r 不是合法浮点数，回退为 %s", key, raw, default)
        return default


def _read_optional_int(
    key: str,
    *,
    env_file_values: dict[str, str],
    default: int | None = None,
    aliases: tuple[str, ...] = (),
) -> int | None:
    """读取可选整数配置。

    空字符串视为“未配置”，返回 `default`。
    """

    raw = _read_str(
        key,
        env_file_values=env_file_values,
        default="" if default is None else str(default),
        aliases=aliases,
    ).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Agent 配置 %s=%r 不是合法整数，回退为 %s",
            key,
            raw,
            default,
        )
        return default


def _resolve_agent_provider(
    *,
    agent_prefix: str,
    env_file_values: dict[str, str],
    default_provider: OpenAIProviderConfig,
) -> OpenAIProviderConfig:
    """解析单个 Agent 的最终 Provider 配置。

    规则是：
    - 先读取共享默认配置 `AGENT_*`
    - 再允许单独 Agent 配置覆盖对应字段

    例如：
    - `AGENT_API_KEY` 作为所有 Agent 的默认 key
    - `PLANNER_AGENT_API_KEY` 只覆盖 Planner 的 key
    """

    return OpenAIProviderConfig(
        api_key=_read_str(
            f"{agent_prefix}_API_KEY",
            env_file_values=env_file_values,
            default=default_provider.api_key,
        ),
        base_url=_read_str(
            f"{agent_prefix}_BASE_URL",
            env_file_values=env_file_values,
            default=default_provider.base_url,
        ),
        organization=_read_str(
            f"{agent_prefix}_ORGANIZATION",
            env_file_values=env_file_values,
            default=default_provider.organization,
        ),
        project=_read_str(
            f"{agent_prefix}_PROJECT",
            env_file_values=env_file_values,
            default=default_provider.project,
        ),
    )


def load_agent_settings(env_path: str | Path | None = None) -> AgentSettings:
    """读取 Agent 运行配置。

    优先级：进程环境变量 > `.env` 文件 > 默认值。
    """

    resolved_env_path = Path(env_path) if env_path is not None else _DEFAULT_ENV_PATH
    env_file_values = _read_env_file(resolved_env_path)

    # 共享默认配置：所有 Agent 默认先继承 AGENT_*。
    default_provider = OpenAIProviderConfig(
        api_key=_read_str(
            "AGENT_API_KEY",
            env_file_values=env_file_values,
            aliases=("OPENAI_API_KEY",),
        ),
        base_url=_read_str(
            "AGENT_BASE_URL",
            env_file_values=env_file_values,
            aliases=("OPENAI_BASE_URL",),
        ),
        organization=_read_str(
            "AGENT_ORGANIZATION",
            env_file_values=env_file_values,
            aliases=("OPENAI_ORGANIZATION",),
        ),
        project=_read_str(
            "AGENT_PROJECT",
            env_file_values=env_file_values,
            aliases=("OPENAI_PROJECT",),
        ),
    )
    planner_provider = _resolve_agent_provider(
        agent_prefix="PLANNER_AGENT",
        env_file_values=env_file_values,
        default_provider=default_provider,
    )
    narrator_provider = _resolve_agent_provider(
        agent_prefix="NARRATOR_AGENT",
        env_file_values=env_file_values,
        default_provider=default_provider,
    )

    planner = AgentModelConfig(
        model=_read_str(
            "PLANNER_AGENT_MODEL",
            env_file_values=env_file_values,
            default="gpt-4o",
        ),
        temperature=_read_float(
            "PLANNER_AGENT_TEMPERATURE",
            env_file_values=env_file_values,
            default=0.7,
        ),
        top_p=_read_float(
            "PLANNER_AGENT_TOP_P",
            env_file_values=env_file_values,
            default=1.0,
        ),
        top_k=_read_optional_int(
            "PLANNER_AGENT_TOP_K",
            env_file_values=env_file_values,
        ),
        timeout_seconds=_read_float(
            "PLANNER_AGENT_TIMEOUT_SECONDS",
            env_file_values=env_file_values,
            default=45.0,
        ),
    )

    narrator = AgentModelConfig(
        model=_read_str(
            "NARRATOR_AGENT_MODEL",
            env_file_values=env_file_values,
            default="gpt-4o",
        ),
        temperature=_read_float(
            "NARRATOR_AGENT_TEMPERATURE",
            env_file_values=env_file_values,
            default=0.9,
        ),
        top_p=_read_float(
            "NARRATOR_AGENT_TOP_P",
            env_file_values=env_file_values,
            default=1.0,
        ),
        top_k=_read_optional_int(
            "NARRATOR_AGENT_TOP_K",
            env_file_values=env_file_values,
        ),
        timeout_seconds=_read_float(
            "NARRATOR_AGENT_TIMEOUT_SECONDS",
            env_file_values=env_file_values,
            default=60.0,
        ),
    )

    return AgentSettings(
        default_provider=default_provider,
        planner_provider=planner_provider,
        narrator_provider=narrator_provider,
        planner=planner,
        narrator=narrator,
    )


def build_openai_client(provider: OpenAIProviderConfig) -> Any:  # noqa: ANN401
    """按 provider 配置构造 AsyncOpenAI 客户端。

    未配置 api_key 或未安装 openai 时返回 None，调用方继续走 fallback。
    """

    if not provider.api_key:
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai 依赖未安装，Agent 将继续走 fallback 模式。")
        return None

    kwargs: dict[str, str] = {"api_key": provider.api_key}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if provider.organization:
        kwargs["organization"] = provider.organization
    if provider.project:
        kwargs["project"] = provider.project
    return AsyncOpenAI(**kwargs)

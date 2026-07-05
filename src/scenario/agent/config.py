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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model_client import (
    AnthropicModelClient,
    ModelClient,
    OpenAICompatibleModelClient,
)

logger = logging.getLogger(__name__)

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
_DEEPSEEK_DEFAULT_PLANNER_TIMEOUT_SECONDS = 90.0
_DEEPSEEK_DEFAULT_NARRATOR_TIMEOUT_SECONDS = 120.0
_DEEPSEEK_DEFAULT_THINKING = "disabled"
_OPENAI_DEFAULT_MODEL = "gpt-4o"
_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_DEFAULT_MODEL = "claude-3-5-sonnet-latest"


@dataclass(frozen=True)
class OpenAIProviderConfig:
    """单个 Agent 的模型端点连接配置。

    字段留空表示“未显式配置”，调用方可继续走 fallback。
    """

    api_key: str = ""
    base_url: str = ""
    organization: str = ""
    project: str = ""
    endpoint_type: str = "auto"
    anthropic_version: str = "2023-06-01"


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
    deepseek_provider: OpenAIProviderConfig
    planner_provider: OpenAIProviderConfig
    narrator_provider: OpenAIProviderConfig
    planner: AgentModelConfig
    narrator: AgentModelConfig
    anthropic_provider: OpenAIProviderConfig = field(
        default_factory=OpenAIProviderConfig
    )
    deepseek_thinking: str = _DEEPSEEK_DEFAULT_THINKING


_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"


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


def _read_deepseek_thinking(env_file_values: dict[str, str]) -> str:
    raw = _read_str(
        "DEEPSEEK_THINKING",
        env_file_values=env_file_values,
        default=_DEEPSEEK_DEFAULT_THINKING,
    ).strip().lower()
    if raw in {"enabled", "disabled"}:
        return raw
    logger.warning(
        "Agent 配置 DEEPSEEK_THINKING=%r 非法，回退为 %s",
        raw,
        _DEEPSEEK_DEFAULT_THINKING,
    )
    return _DEEPSEEK_DEFAULT_THINKING


def _read_endpoint_type(
    key: str,
    *,
    env_file_values: dict[str, str],
    default: str = "auto",
    aliases: tuple[str, ...] = (),
) -> str:
    raw = _read_str(
        key,
        env_file_values=env_file_values,
        default=default,
        aliases=aliases,
    ).strip().lower()
    normalized = raw.replace("_", "-")
    if normalized in {"openai", "openai-compatible", "compatible", "deepseek"}:
        return "openai_compatible"
    if normalized in {"anthropic", "claude"}:
        return "anthropic"
    if normalized in {"auto", ""}:
        return "auto"
    logger.warning("Agent 端点类型 %s=%r 非法，回退为 %s", key, raw, default)
    return default


def _resolve_agent_provider(
    *,
    agent_prefix: str,
    env_file_values: dict[str, str],
    default_provider: OpenAIProviderConfig,
    endpoint_defaults: dict[str, OpenAIProviderConfig] | None = None,
) -> OpenAIProviderConfig:
    """解析单个 Agent 的最终 Provider 配置。

    规则是：
    - 先读取共享默认配置 `AGENT_*`
    - 再允许单独 Agent 配置覆盖对应字段

    例如：
    - `AGENT_API_KEY` 作为所有 Agent 的默认 key
    - `PLANNER_AGENT_API_KEY` 只覆盖 Planner 的 key
    """

    endpoint_type = _read_endpoint_type(
        f"{agent_prefix}_PROVIDER",
        env_file_values=env_file_values,
        default=default_provider.endpoint_type,
        aliases=(f"{agent_prefix}_ENDPOINT_TYPE",),
    )
    inherited_provider = default_provider
    if endpoint_defaults and endpoint_type != default_provider.endpoint_type:
        inherited_provider = endpoint_defaults.get(endpoint_type, default_provider)

    return OpenAIProviderConfig(
        api_key=_read_str(
            f"{agent_prefix}_API_KEY",
            env_file_values=env_file_values,
            default=inherited_provider.api_key,
        ),
        base_url=_read_str(
            f"{agent_prefix}_BASE_URL",
            env_file_values=env_file_values,
            default=inherited_provider.base_url,
        ),
        organization=_read_str(
            f"{agent_prefix}_ORGANIZATION",
            env_file_values=env_file_values,
            default=inherited_provider.organization,
        ),
        project=_read_str(
            f"{agent_prefix}_PROJECT",
            env_file_values=env_file_values,
            default=inherited_provider.project,
        ),
        endpoint_type=endpoint_type,
        anthropic_version=_read_str(
            f"{agent_prefix}_ANTHROPIC_VERSION",
            env_file_values=env_file_values,
            default=inherited_provider.anthropic_version,
        ),
    )


def load_agent_settings(env_path: str | Path | None = None) -> AgentSettings:
    """读取 Agent 运行配置。

    优先级：进程环境变量 > `.env` 文件 > 默认值。
    """

    resolved_env_path = Path(env_path) if env_path is not None else _DEFAULT_ENV_PATH
    env_file_values = _read_env_file(resolved_env_path)
    deepseek_api_key = _read_str(
        "DEEPSEEK_API_KEY",
        env_file_values=env_file_values,
    )
    anthropic_api_key = _read_str(
        "ANTHROPIC_API_KEY",
        env_file_values=env_file_values,
    )
    agent_api_key = _read_str(
        "AGENT_API_KEY",
        env_file_values=env_file_values,
    )
    openai_api_key = _read_str(
        "OPENAI_API_KEY",
        env_file_values=env_file_values,
    )
    explicit_agent_api_key = agent_api_key or openai_api_key
    deepseek_base_url = _read_str(
        "DEEPSEEK_BASE_URL",
        env_file_values=env_file_values,
        default=_DEEPSEEK_DEFAULT_BASE_URL if deepseek_api_key else "",
    )
    agent_base_url = _read_str(
        "AGENT_BASE_URL",
        env_file_values=env_file_values,
    )
    openai_base_url = _read_str(
        "OPENAI_BASE_URL",
        env_file_values=env_file_values,
    )
    anthropic_base_url = _read_str(
        "ANTHROPIC_BASE_URL",
        env_file_values=env_file_values,
        default=_ANTHROPIC_DEFAULT_BASE_URL if anthropic_api_key else "",
    )
    openai_compatible_default_key = (
        agent_api_key or openai_api_key or deepseek_api_key
    )
    openai_compatible_default_base_url = (
        agent_base_url
        or openai_base_url
        or (deepseek_base_url if deepseek_api_key and not explicit_agent_api_key else "")
    )
    anthropic_default_key = agent_api_key or anthropic_api_key
    anthropic_default_base_url = agent_base_url or anthropic_base_url
    legacy_default_api_key = _read_str(
        "AGENT_API_KEY",
        env_file_values=env_file_values,
        default=openai_compatible_default_key,
    )
    default_endpoint_type = _read_endpoint_type(
        "AGENT_PROVIDER",
        env_file_values=env_file_values,
        default=(
            "deepseek"
            if deepseek_api_key and not explicit_agent_api_key
            else "anthropic"
            if anthropic_api_key and not explicit_agent_api_key
            else "auto"
        ),
        aliases=("AGENT_ENDPOINT_TYPE", "MODEL_PROVIDER"),
    )
    if default_endpoint_type == "deepseek":
        default_endpoint_type = "openai_compatible"
    default_api_key = (
        anthropic_default_key
        if default_endpoint_type == "anthropic"
        else legacy_default_api_key
    )
    default_base_url = (
        anthropic_default_base_url
        if default_endpoint_type == "anthropic"
        else openai_compatible_default_base_url
    )

    # 共享默认配置：所有 Agent 默认先继承 AGENT_*。
    default_provider = OpenAIProviderConfig(
        api_key=default_api_key,
        base_url=default_base_url,
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
        endpoint_type=default_endpoint_type,
        anthropic_version=_read_str(
            "ANTHROPIC_VERSION",
            env_file_values=env_file_values,
            default="2023-06-01",
        ),
    )
    deepseek_provider = OpenAIProviderConfig(
        api_key=_read_str(
            "DEEPSEEK_API_KEY",
            env_file_values=env_file_values,
        ),
        base_url=_read_str(
            "DEEPSEEK_BASE_URL",
            env_file_values=env_file_values,
            default=_DEEPSEEK_DEFAULT_BASE_URL,
            aliases=("DEEPSEEK_API_BASE",),
        ),
    )
    anthropic_provider = OpenAIProviderConfig(
        api_key=_read_str(
            "ANTHROPIC_API_KEY",
            env_file_values=env_file_values,
        ),
        base_url=_read_str(
            "ANTHROPIC_BASE_URL",
            env_file_values=env_file_values,
            default=_ANTHROPIC_DEFAULT_BASE_URL,
        ),
        endpoint_type="anthropic",
        anthropic_version=_read_str(
            "ANTHROPIC_VERSION",
            env_file_values=env_file_values,
            default="2023-06-01",
        ),
    )
    planner_provider = _resolve_agent_provider(
        agent_prefix="PLANNER_AGENT",
        env_file_values=env_file_values,
        default_provider=default_provider,
        endpoint_defaults={"anthropic": anthropic_provider},
    )
    narrator_provider = _resolve_agent_provider(
        agent_prefix="NARRATOR_AGENT",
        env_file_values=env_file_values,
        default_provider=default_provider,
        endpoint_defaults={"anthropic": anthropic_provider},
    )
    default_provider_kind = detect_provider_kind(client=default_provider)
    default_model = (
        _DEEPSEEK_DEFAULT_MODEL
        if default_provider_kind == "deepseek"
        else _ANTHROPIC_DEFAULT_MODEL
        if default_provider_kind == "anthropic"
        else _OPENAI_DEFAULT_MODEL
    )
    planner_timeout_default = (
        _DEEPSEEK_DEFAULT_PLANNER_TIMEOUT_SECONDS
        if default_provider_kind == "deepseek"
        else 45.0
    )
    narrator_timeout_default = (
        _DEEPSEEK_DEFAULT_NARRATOR_TIMEOUT_SECONDS
        if default_provider_kind == "deepseek"
        else 60.0
    )

    planner = AgentModelConfig(
        model=_read_str(
            "PLANNER_AGENT_MODEL",
            env_file_values=env_file_values,
            default=default_model,
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
            default=planner_timeout_default,
        ),
    )

    narrator = AgentModelConfig(
        model=_read_str(
            "NARRATOR_AGENT_MODEL",
            env_file_values=env_file_values,
            default=default_model,
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
            default=narrator_timeout_default,
        ),
    )

    return AgentSettings(
        default_provider=default_provider,
        deepseek_provider=deepseek_provider,
        planner_provider=planner_provider,
        narrator_provider=narrator_provider,
        planner=planner,
        narrator=narrator,
        anthropic_provider=anthropic_provider,
        deepseek_thinking=_read_deepseek_thinking(env_file_values),
    )


def select_provider_for_model(
    *,
    model_id: str,
    default_provider: OpenAIProviderConfig,
    deepseek_provider: OpenAIProviderConfig,
    anthropic_provider: OpenAIProviderConfig | None = None,
) -> OpenAIProviderConfig:
    """根据模型名选择实际 Provider。

    DeepSeek 模型优先读取 `DEEPSEEK_API_KEY`，避免误用 `OPENAI_API_KEY`
    去请求 `deepseek-*` 模型。
    """

    provider_kind = detect_provider_kind(model_id=model_id)
    if provider_kind == "deepseek" and deepseek_provider.api_key:
        return OpenAIProviderConfig(
            api_key=deepseek_provider.api_key,
            base_url=deepseek_provider.base_url or _DEEPSEEK_DEFAULT_BASE_URL,
            organization=deepseek_provider.organization,
            project=deepseek_provider.project,
            endpoint_type="openai_compatible",
            anthropic_version=deepseek_provider.anthropic_version,
        )
    if (
        provider_kind == "anthropic"
        and anthropic_provider is not None
        and anthropic_provider.api_key
    ):
        return anthropic_provider
    return default_provider


def build_model_client(
    provider: OpenAIProviderConfig,
    *,
    model_id: str = "",
    openai_client: Any = None,
) -> ModelClient | None:
    """Build a provider-neutral model client for one endpoint."""

    if openai_client is not None:
        provider_kind = detect_provider_kind(model_id=model_id, client=openai_client)
        return OpenAICompatibleModelClient(
            openai_client,
            provider_kind=provider_kind,
        )
    provider_kind = detect_provider_kind(model_id=model_id, client=provider)
    explicit_provider_kind = detect_provider_kind(client=provider)
    if provider_kind == "anthropic" and explicit_provider_kind != "anthropic":
        provider_kind = explicit_provider_kind
    if provider_kind == "anthropic":
        if not provider.api_key:
            return None
        return AnthropicModelClient(
            api_key=provider.api_key,
            base_url=provider.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
            anthropic_version=provider.anthropic_version,
        )
    raw_client = build_openai_client(provider)
    if raw_client is None:
        return None
    return OpenAICompatibleModelClient(
        raw_client,
        provider_kind=detect_provider_kind(model_id=model_id, client=raw_client),
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


def detect_provider_kind(*, model_id: str = "", client: Any = None) -> str:  # noqa: ANN401
    """根据模型名和客户端 base_url 推断 Provider 类型。

    返回值用于决定 response_format：
    - ``deepseek``: DeepSeek 专属，需要 extra_body thinking 参数
    - ``json_object_only``: 仅支持 ``{"type": "json_object"}``，不支持
      OpenAI ``json_schema`` 结构化输出（如 LongCat 等兼容接口）
    - ``openai_compatible``: 完整 OpenAI 特性，支持 json_schema
    """

    base_url = str(getattr(client, "base_url", "") or "").lower()
    endpoint_type = str(getattr(client, "endpoint_type", "") or "").lower()
    model = model_id.lower()
    if (
        endpoint_type == "anthropic"
        or "anthropic.com" in base_url
        or model.startswith("claude")
    ):
        return "anthropic"
    if "deepseek.com" in base_url or model.startswith("deepseek-"):
        return "deepseek"
    if "longcat" in base_url or model.startswith("longcat"):
        return "json_object_only"
    return "openai_compatible"


def supports_json_schema(provider_kind: str) -> bool:
    """仅当 provider 支持 OpenAI json_schema 结构化输出时返回 True。"""

    return provider_kind == "openai_compatible"

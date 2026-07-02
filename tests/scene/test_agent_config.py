from __future__ import annotations

import sys

from scenario.runtime.engine import KeeperPlanAgent, KeeperRenderAgent


def test_planner_agent_reads_defaults_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("PLANNER_AGENT_MODEL", "planner-demo-model")
    monkeypatch.setenv("PLANNER_AGENT_TEMPERATURE", "0.33")
    monkeypatch.setenv("PLANNER_AGENT_TOP_P", "0.88")
    monkeypatch.setenv("PLANNER_AGENT_TOP_K", "12")
    monkeypatch.setenv("PLANNER_AGENT_TIMEOUT_SECONDS", "91")
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PLANNER_AGENT_API_KEY", raising=False)
    planner_module = sys.modules[KeeperPlanAgent.__module__]
    monkeypatch.setattr(planner_module, "build_openai_client", lambda provider: None)

    agent = KeeperPlanAgent()

    assert agent.model_id == "planner-demo-model"
    assert agent._temperature == 0.33
    assert agent._top_p == 0.88
    assert agent._top_k == 12
    assert agent.timeout_seconds == 91.0
    assert agent._client is None


def test_narrator_agent_reads_defaults_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("NARRATOR_AGENT_MODEL", "narrator-demo-model")
    monkeypatch.setenv("NARRATOR_AGENT_TEMPERATURE", "0.44")
    monkeypatch.setenv("NARRATOR_AGENT_TOP_P", "0.77")
    monkeypatch.setenv("NARRATOR_AGENT_TOP_K", "9")
    monkeypatch.setenv("NARRATOR_AGENT_TIMEOUT_SECONDS", "72")
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NARRATOR_AGENT_API_KEY", raising=False)
    narrator_module = sys.modules[KeeperRenderAgent.__module__]
    monkeypatch.setattr(narrator_module, "build_openai_client", lambda provider: None)

    agent = KeeperRenderAgent()

    assert agent.model_id == "narrator-demo-model"
    assert agent._temperature == 0.44
    assert agent._top_p == 0.77
    assert agent._top_k == 9
    assert agent.timeout_seconds == 72.0
    assert agent._client is None


def test_agent_settings_use_shared_provider_as_default_and_allow_overrides(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "shared-key")
    monkeypatch.setenv("AGENT_BASE_URL", "https://shared.example/v1")
    monkeypatch.setenv("AGENT_ORGANIZATION", "shared-org")
    monkeypatch.setenv("AGENT_PROJECT", "shared-project")
    monkeypatch.setenv("PLANNER_AGENT_API_KEY", "planner-key")
    monkeypatch.setenv("NARRATOR_AGENT_BASE_URL", "https://narrator.example/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    planner_module = sys.modules[KeeperPlanAgent.__module__]
    narrator_module = sys.modules[KeeperRenderAgent.__module__]
    captured: dict[str, object] = {}

    def _capture_planner(provider):
        captured["planner"] = provider
        return object()

    def _capture_narrator(provider):
        captured["narrator"] = provider
        return object()

    monkeypatch.setattr(planner_module, "build_openai_client", _capture_planner)
    monkeypatch.setattr(narrator_module, "build_openai_client", _capture_narrator)

    planner = KeeperPlanAgent()
    narrator = KeeperRenderAgent()

    planner_provider = captured["planner"]
    narrator_provider = captured["narrator"]

    assert planner._client is not None
    assert narrator._client is not None
    assert planner_provider.api_key == "planner-key"
    assert planner_provider.base_url == "https://shared.example/v1"
    assert planner_provider.organization == "shared-org"
    assert planner_provider.project == "shared-project"
    assert narrator_provider.api_key == "shared-key"
    assert narrator_provider.base_url == "https://narrator.example/v1"
    assert narrator_provider.organization == "shared-org"
    assert narrator_provider.project == "shared-project"

def test_agent_settings_accept_deepseek_api_key_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("PLANNER_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("PLANNER_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("PLANNER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("NARRATOR_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("NARRATOR_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("NARRATOR_AGENT_MODEL", raising=False)

    planner_module = sys.modules[KeeperPlanAgent.__module__]
    narrator_module = sys.modules[KeeperRenderAgent.__module__]
    captured: dict[str, object] = {}

    def _capture_planner(provider):
        captured["planner"] = provider
        return object()

    def _capture_narrator(provider):
        captured["narrator"] = provider
        return object()

    monkeypatch.setattr(planner_module, "build_openai_client", _capture_planner)
    monkeypatch.setattr(narrator_module, "build_openai_client", _capture_narrator)

    planner = KeeperPlanAgent()
    narrator = KeeperRenderAgent()

    planner_provider = captured["planner"]
    narrator_provider = captured["narrator"]

    assert planner.model_id == "deepseek-v4-pro"
    assert narrator.model_id == "deepseek-v4-pro"
    assert planner.timeout_seconds == 90.0
    assert narrator.timeout_seconds == 120.0
    assert planner._deepseek_thinking == "disabled"
    assert narrator._deepseek_thinking == "disabled"
    assert planner._provider_kind == "deepseek"
    assert narrator._provider_kind == "deepseek"
    assert planner_provider.api_key == "deepseek-key"
    assert narrator_provider.api_key == "deepseek-key"
    assert planner_provider.base_url == "https://api.deepseek.com"
    assert narrator_provider.base_url == "https://api.deepseek.com"


def test_agent_settings_accept_deepseek_thinking_override(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_THINKING", "enabled")

    planner_module = sys.modules[KeeperPlanAgent.__module__]
    narrator_module = sys.modules[KeeperRenderAgent.__module__]
    monkeypatch.setattr(planner_module, "build_openai_client", lambda provider: object())
    monkeypatch.setattr(narrator_module, "build_openai_client", lambda provider: object())

    assert KeeperPlanAgent()._deepseek_thinking == "enabled"
    assert KeeperRenderAgent()._deepseek_thinking == "enabled"


def test_deepseek_model_prefers_deepseek_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_BASE", raising=False)

    planner_module = sys.modules[KeeperPlanAgent.__module__]
    captured: dict[str, object] = {}

    def _capture_planner(provider):
        captured["planner"] = provider
        return object()

    monkeypatch.setattr(planner_module, "build_openai_client", _capture_planner)

    agent = KeeperPlanAgent(model_id="deepseek-v4-flash")

    planner_provider = captured["planner"]
    assert agent._client is not None
    assert planner_provider.api_key == "deepseek-key"
    assert planner_provider.base_url == "https://api.deepseek.com"

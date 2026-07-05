"""Tests for PromptBuilder injecting KTSL context into AgentPlanPrompt."""
from __future__ import annotations


from scenario.agent.models import AgentPlanPrompt
from scenario.agent.prompt_builder import PromptBuilder
from scenario.ktsl.models import KTSLLedger
from scenario.module.models import ModuleDefinition, ModuleScene
from scenario.session.state import SessionMapState
from scenario.story.models import StoryState


class TestPromptBuilderKTSLIntegration:
    @staticmethod
    def _make_module() -> ModuleDefinition:
        return ModuleDefinition(
            module_id="test_mod",
            title="Test Mod",
            entry_scene_id="library",
            entry_stage_id="entry",
            scenes=[ModuleScene(id="library", name="Library")],
        )

    @staticmethod
    def _make_session_with_ledger() -> SessionMapState:
        ledger = KTSLLedger.empty(module_id="test_mod")
        return SessionMapState(
            session_id="s1",
            module_id="test_mod",
            current_turn=1,
            global_flags=set(),
            story_state=StoryState(current_stage_id="entry"),
            clock_values={},
            completed_actions=set(),
            triggered_clock_events=set(),
            scene_instances={},
            player_states={},
            pending_intents={},
            npc_states={},
            npc_patch_queue=[],
            ktsl_ledger=ledger,
        )

    @staticmethod
    def _make_session_without_ledger() -> SessionMapState:
        return SessionMapState(
            session_id="s1",
            module_id="m",
            current_turn=1,
            global_flags=set(),
            story_state=StoryState(current_stage_id="entry"),
            clock_values={},
            completed_actions=set(),
            triggered_clock_events=set(),
            scene_instances={},
            player_states={},
            pending_intents={},
            npc_states={},
            npc_patch_queue=[],
        )

    def test_build_includes_ktsl_context_when_ledger_attached(self) -> None:
        builder = PromptBuilder()
        session = self._make_session_with_ledger()
        module = self._make_module()
        prompt = builder.build(
            session=session,
            module=module,
            scene_id="library",
            recent_events=[],
        )
        assert isinstance(prompt, AgentPlanPrompt)
        assert prompt.ktsl_context is not None

    def test_build_omits_ktsl_context_when_no_ledger(self) -> None:
        builder = PromptBuilder()
        session = self._make_session_without_ledger()
        module = self._make_module()
        prompt = builder.build(
            session=session, module=module, scene_id="library"
        )
        assert isinstance(prompt, AgentPlanPrompt)
        assert prompt.ktsl_context is None

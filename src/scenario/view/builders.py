"""从运行时对象构建可见视图。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..agent.models import VisibleScope
from ..module.models import ModuleDefinition
from ..session.state import SessionMapState
from .models import (
    KeeperSceneNarrationView,
    KeeperSessionView,
    KeeperTurnView,
    PlayerActionView,
    PlayerSceneNarrationView,
    PlayerSessionView,
    PlayerTurnView,
    PrivateClueView,
    PublicDialogueView,
)

if TYPE_CHECKING:
    from ..runtime.contracts import TurnResolution
    from ..runtime.engine import SceneRuntime


class TurnViewBuilder:
    """把一次 TurnResolution 过滤成玩家/守密人视图。"""

    def build_player_turn_view(
        self,
        *,
        resolution: "TurnResolution",
        session: SessionMapState,
        player_id: str,
    ) -> PlayerTurnView:
        if player_id not in session.player_states:
            raise KeyError(f"未知玩家: {player_id}")
        player_state = session.player_states[player_id]
        scenes: list[PlayerSceneNarrationView] = []
        for batch in resolution.scene_batches:
            if player_id not in batch.player_ids:
                continue
            narration = batch.narration
            scenes.append(
                PlayerSceneNarrationView(
                    scene_id=batch.scene_id,
                    outcomes=[
                        outcome
                        for outcome in batch.outcomes
                        if outcome.player_id == player_id
                    ],
                    public_narration=getattr(narration, "public_narration", ""),
                    npc_dialogues=self._public_dialogues(narration),
                    private_clues=self._private_clues_for_player(
                        narration,
                        player_id=player_id,
                    ),
                    is_fallback=bool(getattr(narration, "is_fallback", False)),
                )
            )
        return PlayerTurnView(
            session_id=resolution.session_id,
            turn_no=resolution.turn_no,
            next_turn=resolution.next_turn,
            player_id=player_id,
            current_scene_id=player_state.current_scene_id,
            current_stage_id=resolution.current_stage_id
            or session.story_state.current_stage_id,
            resolved_ending=resolution.resolved_ending or session.resolved_ending,
            scenes=scenes,
        )

    def build_keeper_turn_view(
        self,
        *,
        resolution: "TurnResolution",
        session: SessionMapState,
    ) -> KeeperTurnView:
        scenes: list[KeeperSceneNarrationView] = []
        for batch in resolution.scene_batches:
            narration = batch.narration
            scenes.append(
                KeeperSceneNarrationView(
                    scene_id=batch.scene_id,
                    player_ids=batch.player_ids,
                    outcomes=batch.outcomes,
                    public_narration=getattr(narration, "public_narration", ""),
                    npc_dialogues=self._all_dialogues(narration),
                    private_clues=self._all_private_clues(narration),
                    keeper_hint=getattr(narration, "keeper_hint", ""),
                    is_fallback=bool(getattr(narration, "is_fallback", False)),
                )
            )
        return KeeperTurnView(
            session_id=resolution.session_id,
            turn_no=resolution.turn_no,
            next_turn=resolution.next_turn,
            current_stage_id=resolution.current_stage_id
            or session.story_state.current_stage_id,
            resolved_ending=resolution.resolved_ending or session.resolved_ending,
            scenes=scenes,
            event_log=resolution.event_log,
        )

    def _public_dialogues(self, narration: object) -> list[PublicDialogueView]:
        result: list[PublicDialogueView] = []
        for dialogue in getattr(narration, "npc_dialogues", []) or []:
            visible_scope = getattr(dialogue, "visible_scope", VisibleScope.PUBLIC)
            if visible_scope != VisibleScope.PUBLIC:
                continue
            result.append(self._dialogue_view(dialogue))
        return result

    def _all_dialogues(self, narration: object) -> list[PublicDialogueView]:
        return [
            self._dialogue_view(dialogue)
            for dialogue in getattr(narration, "npc_dialogues", []) or []
        ]

    def _dialogue_view(self, dialogue: object) -> PublicDialogueView:
        return PublicDialogueView(
            npc_id=str(getattr(dialogue, "npc_id", "")),
            npc_name=str(getattr(dialogue, "npc_name", "")),
            dialogue=str(getattr(dialogue, "dialogue", "")),
        )

    def _private_clues_for_player(
        self,
        narration: object,
        *,
        player_id: str,
    ) -> list[PrivateClueView]:
        return [
            self._private_clue_view(clue)
            for clue in getattr(narration, "private_clues", []) or []
            if getattr(clue, "player_id", "") == player_id
        ]

    def _all_private_clues(self, narration: object) -> list[PrivateClueView]:
        return [
            self._private_clue_view(clue)
            for clue in getattr(narration, "private_clues", []) or []
        ]

    def _private_clue_view(self, clue: object) -> PrivateClueView:
        return PrivateClueView(
            player_id=str(getattr(clue, "player_id", "")),
            clue_text=str(getattr(clue, "clue_text", "")),
            related_action_id=str(getattr(clue, "related_action_id", "")),
        )


class ScenarioViewBuilder:
    """构建当前会话状态的玩家/守密人视图。"""

    def build_player_session_view(
        self,
        *,
        runtime: "SceneRuntime",
        session: SessionMapState,
        module: ModuleDefinition,
        player_id: str,
    ) -> PlayerSessionView:
        if player_id not in session.player_states:
            raise KeyError(f"未知玩家: {player_id}")
        player_state = session.player_states[player_id]
        scene = module.scene_map()[player_state.current_scene_id]
        return PlayerSessionView(
            session_id=session.session_id,
            module_id=session.module_id,
            player_id=player_id,
            current_turn=session.current_turn,
            current_stage_id=session.story_state.current_stage_id,
            current_scene_id=scene.id,
            current_scene_name=scene.name,
            current_scene_description=scene.description,
            reachable_scene_ids=runtime.list_reachable_scenes(session, player_id),
            available_actions=[
                PlayerActionView(
                    action_id=action.id,
                    name=action.name,
                    kind=action.kind,
                    description=action.description,
                    stakes=action.stakes,
                )
                for action in runtime.list_available_actions(session, player_id)
            ],
            pending_intent_submitted=player_id in session.pending_intents,
            resolved_ending=session.resolved_ending,
        )

    def build_keeper_session_view(
        self,
        *,
        session: SessionMapState,
    ) -> KeeperSessionView:
        return KeeperSessionView(
            session_id=session.session_id,
            module_id=session.module_id,
            current_turn=session.current_turn,
            current_stage_id=session.story_state.current_stage_id,
            player_scene_ids={
                player_id: state.current_scene_id
                for player_id, state in sorted(session.player_states.items())
            },
            global_flags=sorted(session.global_flags),
            clock_values=dict(session.clock_values),
            completed_actions=sorted(session.completed_actions),
            pending_players=sorted(session.pending_intents),
            resolved_ending=session.resolved_ending,
        )

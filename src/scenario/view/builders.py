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
                    public_narration=str(
                        self._value(narration, "public_narration", "")
                    ),
                    npc_dialogues=self._public_dialogues(narration),
                    private_clues=self._private_clues_for_player(
                        narration,
                        player_id=player_id,
                    ),
                    is_fallback=bool(
                        self._value(narration, "is_fallback", False)
                    ),
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
            hit_points=player_state.investigator.state.hit_points,
            sanity=player_state.investigator.state.sanity,
            physical_state=str(player_state.investigator.state.physical_state),
            mental_state=str(player_state.investigator.state.mental_state),
            special_state=player_state.investigator.state.special_state,
            resolved_ending=resolution.resolved_ending or session.resolved_ending,
            scenes=scenes,
            dice_rolls=[
                roll
                for roll in resolution.dice_rolls
                if self._value(roll, "player_id", "") == player_id
                and self._value(roll, "visibility", "public") == "public"
            ],
            clues=self._player_clues(session, player_id=player_id),
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
                    public_narration=str(
                        self._value(narration, "public_narration", "")
                    ),
                    npc_dialogues=self._all_dialogues(narration),
                    private_clues=self._all_private_clues(narration),
                    keeper_hint=str(self._value(narration, "keeper_hint", "")),
                    is_fallback=bool(
                        self._value(narration, "is_fallback", False)
                    ),
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
            dice_rolls=resolution.dice_rolls,
            clues=self._keeper_clues(session),
            route_coverage=self._route_coverage(session),
            disconnected_route_ids=self._disconnected_route_ids(session),
        )

    def _player_clues(
        self,
        session: SessionMapState,
        *,
        player_id: str,
    ) -> list[object]:
        if session.clue_graph is None:
            return []
        return session.clue_graph.player_view(
            session.session_clues,
            player_id=player_id,
        )

    def _keeper_clues(self, session: SessionMapState) -> list[object]:
        if session.clue_graph is None:
            return []
        return session.clue_graph.keeper_view(session.session_clues)

    def _route_coverage(self, session: SessionMapState) -> dict[str, object]:
        if session.clue_graph is None:
            return {}
        return session.clue_graph.core_route_coverage(session.session_clues)

    def _disconnected_route_ids(self, session: SessionMapState) -> list[str]:
        return sorted(
            route_id
            for route_id, coverage in self._route_coverage(session).items()
            if not coverage.is_reachable
        )

    def _public_dialogues(self, narration: object) -> list[PublicDialogueView]:
        result: list[PublicDialogueView] = []
        for dialogue in self._list_value(narration, "npc_dialogues"):
            visible_scope = self._value(
                dialogue,
                "visible_scope",
                VisibleScope.PUBLIC,
            )
            if visible_scope != VisibleScope.PUBLIC:
                continue
            result.append(self._dialogue_view(dialogue))
        return result

    def _all_dialogues(self, narration: object) -> list[PublicDialogueView]:
        return [
            self._dialogue_view(dialogue)
            for dialogue in self._list_value(narration, "npc_dialogues")
        ]

    def _dialogue_view(self, dialogue: object) -> PublicDialogueView:
        return PublicDialogueView(
            npc_id=str(self._value(dialogue, "npc_id", "")),
            npc_name=str(self._value(dialogue, "npc_name", "")),
            dialogue=str(self._value(dialogue, "dialogue", "")),
        )

    def _private_clues_for_player(
        self,
        narration: object,
        *,
        player_id: str,
    ) -> list[PrivateClueView]:
        return [
            self._private_clue_view(clue)
            for clue in self._list_value(narration, "private_clues")
            if self._value(clue, "player_id", "") == player_id
        ]

    def _all_private_clues(self, narration: object) -> list[PrivateClueView]:
        return [
            self._private_clue_view(clue)
            for clue in self._list_value(narration, "private_clues")
        ]

    def _private_clue_view(self, clue: object) -> PrivateClueView:
        return PrivateClueView(
            player_id=str(self._value(clue, "player_id", "")),
            clue_text=str(self._value(clue, "clue_text", "")),
            related_action_id=str(self._value(clue, "related_action_id", "")),
        )

    def _value(self, item: object, key: str, default: object) -> object:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _list_value(self, item: object, key: str) -> list[object]:
        value = self._value(item, key, [])
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return []


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
            hit_points=player_state.investigator.state.hit_points,
            sanity=player_state.investigator.state.sanity,
            physical_state=str(player_state.investigator.state.physical_state),
            mental_state=str(player_state.investigator.state.mental_state),
            special_state=player_state.investigator.state.special_state,
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
            clues=(
                session.clue_graph.player_view(
                    session.session_clues,
                    player_id=player_id,
                )
                if session.clue_graph is not None
                else []
            ),
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
            clues=(
                session.clue_graph.keeper_view(session.session_clues)
                if session.clue_graph is not None
                else []
            ),
            route_coverage=(
                session.clue_graph.core_route_coverage(session.session_clues)
                if session.clue_graph is not None
                else {}
            ),
            disconnected_route_ids=(
                sorted(
                    route_id
                    for route_id, coverage in session.clue_graph.core_route_coverage(
                        session.session_clues
                    ).items()
                    if not coverage.is_reachable
                )
                if session.clue_graph is not None
                else []
            ),
        )

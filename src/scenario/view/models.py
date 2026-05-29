"""玩家与守密人可见视图模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlayerActionView(BaseModel):
    action_id: str
    name: str
    kind: str


class PublicDialogueView(BaseModel):
    npc_id: str
    npc_name: str = ""
    dialogue: str


class PrivateClueView(BaseModel):
    player_id: str
    clue_text: str
    related_action_id: str = ""


class PlayerSceneNarrationView(BaseModel):
    scene_id: str
    outcomes: list[Any] = Field(default_factory=list)
    public_narration: str = ""
    npc_dialogues: list[PublicDialogueView] = Field(default_factory=list)
    private_clues: list[PrivateClueView] = Field(default_factory=list)
    is_fallback: bool = False


class KeeperSceneNarrationView(BaseModel):
    scene_id: str
    player_ids: list[str] = Field(default_factory=list)
    outcomes: list[Any] = Field(default_factory=list)
    public_narration: str = ""
    npc_dialogues: list[PublicDialogueView] = Field(default_factory=list)
    private_clues: list[PrivateClueView] = Field(default_factory=list)
    keeper_hint: str = ""
    is_fallback: bool = False


class PlayerTurnView(BaseModel):
    session_id: str
    turn_no: int
    next_turn: int
    player_id: str
    current_scene_id: str
    current_stage_id: str
    resolved_ending: str | None = None
    scenes: list[PlayerSceneNarrationView] = Field(default_factory=list)


class KeeperTurnView(BaseModel):
    session_id: str
    turn_no: int
    next_turn: int
    current_stage_id: str
    resolved_ending: str | None = None
    scenes: list[KeeperSceneNarrationView] = Field(default_factory=list)
    event_log: list[Any] = Field(default_factory=list)


class PlayerSessionView(BaseModel):
    session_id: str
    module_id: str
    player_id: str
    current_turn: int
    current_stage_id: str
    current_scene_id: str
    current_scene_name: str
    current_scene_description: str = ""
    reachable_scene_ids: list[str] = Field(default_factory=list)
    available_actions: list[PlayerActionView] = Field(default_factory=list)
    pending_intent_submitted: bool = False
    resolved_ending: str | None = None


class KeeperSessionView(BaseModel):
    session_id: str
    module_id: str
    current_turn: int
    current_stage_id: str
    player_scene_ids: dict[str, str] = Field(default_factory=dict)
    global_flags: list[str] = Field(default_factory=list)
    clock_values: dict[str, int] = Field(default_factory=dict)
    completed_actions: list[str] = Field(default_factory=list)
    pending_players: list[str] = Field(default_factory=list)
    resolved_ending: str | None = None

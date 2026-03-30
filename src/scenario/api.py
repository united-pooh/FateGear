"""场景运行时的轻量 API 服务。"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Literal

from cards import build_investigator_card
from cards.domain.card import InvestigatorCard
from pydantic import BaseModel, Field

from .io import MODULE_ROOT, load_module_by_id
from .runtime import SceneRuntime
from .session import SessionMapState


class ModuleSummary(BaseModel):
    module_id: str
    title: str
    entry_scene_id: str
    entry_stage_id: str


class CreatePartyRequest(BaseModel):
    module_id: str = Field(..., min_length=1, max_length=30)
    creator_id: str = Field(..., min_length=1, max_length=30)


class JoinPartyRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=30)


class PartyPlayerSummary(BaseModel):
    player_id: str
    current_scene_id: str
    last_scene_id: str


class PartySummary(BaseModel):
    session_id: str
    module_id: str
    owner_id: str
    current_turn: int
    current_stage_id: str
    resolved_ending: str | None = None
    status: Literal["waiting", "active", "ended"]
    pending_players: list[str] = Field(default_factory=list)
    players: list[PartyPlayerSummary] = Field(default_factory=list)


class ScenarioService:
    """提供建团、查团、加入团等最小接口能力。"""

    def __init__(
        self,
        *,
        runtime: SceneRuntime | None = None,
        module_root: str | Path | None = None,
    ) -> None:
        resolved_module_root = (
            Path(module_root) if module_root is not None else MODULE_ROOT
        )
        self._module_root = resolved_module_root
        self._runtime = runtime or SceneRuntime(module_root=resolved_module_root)
        self._owner_by_session_id: dict[str, str] = {}
        self._lock = RLock()

    def list_modules(self) -> list[ModuleSummary]:
        if not self._module_root.exists():
            return []

        modules: list[ModuleSummary] = []
        for module_dir in sorted(self._module_root.iterdir(), key=lambda item: item.name):
            if not module_dir.is_dir():
                continue
            if not (module_dir / "module.yaml").is_file():
                continue
            definition = load_module_by_id(module_dir.name, module_root=self._module_root)
            modules.append(
                ModuleSummary(
                    module_id=definition.module_id,
                    title=definition.title,
                    entry_scene_id=definition.entry_scene_id,
                    entry_stage_id=definition.entry_stage_id,
                )
            )
        return modules

    def create_party(
        self,
        request: CreatePartyRequest | dict[str, object],
    ) -> PartySummary:
        payload = (
            request
            if isinstance(request, CreatePartyRequest)
            else CreatePartyRequest.model_validate(request)
        )
        with self._lock:
            session = self._runtime.create_session(
                payload.module_id,
                [payload.creator_id],
                player_cards={
                    payload.creator_id: self._build_default_investigator_card(
                        payload.creator_id
                    )
                },
            )
            self._owner_by_session_id[session.session_id] = payload.creator_id
            return self._build_party_summary(session)

    def join_party(
        self,
        session_id: str,
        request: JoinPartyRequest | dict[str, object],
    ) -> PartySummary:
        payload = (
            request
            if isinstance(request, JoinPartyRequest)
            else JoinPartyRequest.model_validate(request)
        )
        with self._lock:
            self._runtime.add_player(
                session_id,
                payload.player_id,
                investigator=self._build_default_investigator_card(payload.player_id),
            )
            session = self._runtime.get_session(session_id)
            return self._build_party_summary(session)

    def get_party(self, session_id: str) -> PartySummary:
        with self._lock:
            session = self._runtime.get_session(session_id)
            return self._build_party_summary(session)

    def list_parties(self) -> list[PartySummary]:
        with self._lock:
            return [
                self._build_party_summary(self._runtime.get_session(session_id))
                for session_id in sorted(self._owner_by_session_id)
            ]

    def _build_party_summary(self, session: SessionMapState) -> PartySummary:
        owner_id = self._owner_by_session_id.get(
            session.session_id,
            next(iter(sorted(session.player_states))),
        )
        if (
            session.resolved_ending is not None
            or session.story_state.resolved_ending_id is not None
        ):
            status: Literal["waiting", "active", "ended"] = "ended"
        elif session.current_turn == 1 and not session.pending_intents:
            status = "waiting"
        else:
            status = "active"

        players = [
            PartyPlayerSummary(
                player_id=player_state.player_id,
                current_scene_id=player_state.current_scene_id,
                last_scene_id=player_state.last_scene_id,
            )
            for player_state in sorted(
                session.player_states.values(),
                key=lambda item: item.player_id,
            )
        ]
        return PartySummary(
            session_id=session.session_id,
            module_id=session.module_id,
            owner_id=owner_id,
            current_turn=session.current_turn,
            current_stage_id=session.story_state.current_stage_id,
            resolved_ending=session.resolved_ending,
            status=status,
            pending_players=sorted(session.pending_intents),
            players=players,
        )

    def _build_default_investigator_card(self, player_id: str) -> InvestigatorCard:
        # FIXME: 默认姓名直接拼接 player_id，长 player_id 可能超过 Name 的 30 字符上限并触发校验失败。
        # FIXME: 默认卡目前不挂技能；在动作配置了 check 的模组中，这会导致会话虽可创建但关键动作难以推进。
        return build_investigator_card(
            name=f"调查员-{player_id}",
            age=25,
            occupation="临时调查员",
            player=player_id,
            strength=50,
            constitution=50,
            size=50,
            dexterity=50,
            appearance=50,
            intelligence=50,
            power=50,
            education=50,
        )

"""场景运行时的轻量 API 服务。"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from threading import RLock
from typing import Literal

from cards import build_investigator_card, load_skill_template_mapping
from cards.domain.card import InvestigatorCard
from cards.domain.skills import SkillTemplate
from pydantic import BaseModel, Field

from .intent import IntentNormalizer, NormalizedIntentResult, RawPlayerIntent
from .io import MODULE_ROOT, load_module_by_id
from .module.models import ModuleDefinition
from .runtime import SceneIntent, SceneRuntime, TurnResolution
from .session import SessionMapState
from .view import KeeperSessionView, KeeperTurnView, PlayerSessionView, PlayerTurnView
from .view import ScenarioViewBuilder, TurnViewBuilder


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


class SubmitIntentRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=30)
    intent: SceneIntent


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


class SubmitTextIntentResponse(BaseModel):
    accepted: bool
    normalization: NormalizedIntentResult
    party: PartySummary | None = None


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
        self._skill_templates = load_skill_template_mapping()
        self._scenario_view_builder = ScenarioViewBuilder()
        self._turn_view_builder = TurnViewBuilder()
        self._intent_normalizer = IntentNormalizer()

    def list_modules(self) -> list[ModuleSummary]:
        """扫描模组目录并返回可创建会话的模组摘要。"""
        if not self._module_root.exists():
            return []

        modules: list[ModuleSummary] = []
        for module_dir in sorted(
            self._module_root.iterdir(), key=lambda item: item.name
        ):
            if not module_dir.is_dir():
                continue
            if not (module_dir / "module.yaml").is_file():
                continue
            definition = load_module_by_id(
                module_dir.name, module_root=self._module_root
            )
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
        """创建新会话，并自动为创建者生成默认调查员卡。"""
        payload = (
            request
            if isinstance(request, CreatePartyRequest)
            else CreatePartyRequest.model_validate(request)
        )
        module = load_module_by_id(
            payload.module_id,
            module_root=self._module_root,
        )
        with self._lock:
            session = self._runtime.create_session(
                payload.module_id,
                [payload.creator_id],
                player_cards={
                    payload.creator_id: self._build_default_investigator_card(
                        payload.creator_id,
                        module_id=payload.module_id,
                        module=module,
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
        """向等待中的会话加入新玩家。"""
        payload = (
            request
            if isinstance(request, JoinPartyRequest)
            else JoinPartyRequest.model_validate(request)
        )
        session = self._runtime.get_session(session_id)
        module = load_module_by_id(session.module_id, module_root=self._module_root)
        with self._lock:
            self._runtime.add_player(
                session_id,
                payload.player_id,
                investigator=self._build_default_investigator_card(
                    payload.player_id,
                    module_id=session.module_id,
                    module=module,
                ),
            )
            session = self._runtime.get_session(session_id)
            return self._build_party_summary(session)

    def submit_intent(
        self,
        session_id: str,
        request: SubmitIntentRequest | dict[str, object],
    ) -> PartySummary:
        """向会话提交本回合玩家意图。"""
        payload = (
            request
            if isinstance(request, SubmitIntentRequest)
            else SubmitIntentRequest.model_validate(request)
        )
        with self._lock:
            self._runtime.submit_intent(
                session_id,
                payload.player_id,
                payload.intent,
            )
            session = self._runtime.get_session(session_id)
            return self._build_party_summary(session)

    async def resolve_turn(
        self,
        session_id: str,
        *,
        expected_turn: int | None = None,
    ) -> TurnResolution:
        """结算当前会话的一个完整回合。"""
        return await self._runtime.resolve_turn(
            session_id,
            expected_turn=expected_turn,
        )

    def get_turn_resolution(self, session_id: str, turn_no: int) -> TurnResolution:
        """读取已结算回合结果。"""
        return self._runtime.get_turn_resolution(session_id, turn_no)

    def list_resolved_turns(self, session_id: str) -> list[int]:
        """列出已结算回合编号。"""
        return self._runtime.list_resolved_turns(session_id)

    def build_player_turn_view(
        self,
        *,
        resolution: TurnResolution,
        player_id: str,
    ) -> PlayerTurnView:
        """把内部 TurnResolution 投影为单个玩家可见的回合视图。"""
        with self._lock:
            session = self._runtime.get_session(resolution.session_id)
            return self._turn_view_builder.build_player_turn_view(
                resolution=resolution,
                session=session,
                player_id=player_id,
            )

    def build_keeper_turn_view(
        self,
        *,
        resolution: TurnResolution,
    ) -> KeeperTurnView:
        """把内部 TurnResolution 投影为守密人视图。"""
        with self._lock:
            session = self._runtime.get_session(resolution.session_id)
            return self._turn_view_builder.build_keeper_turn_view(
                resolution=resolution,
                session=session,
            )

    def get_party(self, session_id: str) -> PartySummary:
        """查询单个会话摘要。"""
        with self._lock:
            session = self._runtime.get_session(session_id)
            return self._build_party_summary(session)

    def submit_text_intent(
        self,
        session_id: str,
        request: RawPlayerIntent | dict[str, object],
    ) -> SubmitTextIntentResponse:
        """提交自然语言意图；可明确归一化时自动写入 pending intent。"""
        payload = (
            request
            if isinstance(request, RawPlayerIntent)
            else RawPlayerIntent.model_validate(request)
        )
        with self._lock:
            session = self._runtime.get_session(session_id)
            module = load_module_by_id(session.module_id, module_root=self._module_root)
            normalization = self._intent_normalizer.normalize(
                runtime=self._runtime,
                session=session,
                module=module,
                player_id=payload.player_id,
                raw_text=payload.text,
            )
            if not normalization.accepted or normalization.intent_payload is None:
                return SubmitTextIntentResponse(
                    accepted=False,
                    normalization=normalization,
                    party=self._build_party_summary(session),
                )
            self._runtime.submit_intent(
                session_id,
                payload.player_id,
                normalization.intent_payload,
            )
            session = self._runtime.get_session(session_id)
            return SubmitTextIntentResponse(
                accepted=True,
                normalization=normalization,
                party=self._build_party_summary(session),
            )

    def get_player_view(self, session_id: str, player_id: str) -> PlayerSessionView:
        """查询单个玩家当前可见会话视图。"""
        with self._lock:
            session = self._runtime.get_session(session_id)
            module = load_module_by_id(session.module_id, module_root=self._module_root)
            return self._scenario_view_builder.build_player_session_view(
                runtime=self._runtime,
                session=session,
                module=module,
                player_id=player_id,
            )

    def get_keeper_view(self, session_id: str) -> KeeperSessionView:
        """查询守密人当前会话视图。"""
        with self._lock:
            session = self._runtime.get_session(session_id)
            return self._scenario_view_builder.build_keeper_session_view(
                session=session
            )

    def list_parties(self) -> list[PartySummary]:
        """列出当前服务进程内管理的会话摘要。"""
        with self._lock:
            return [
                self._build_party_summary(self._runtime.get_session(session_id))
                for session_id in sorted(self._owner_by_session_id)
            ]

    def _build_party_summary(self, session: SessionMapState) -> PartySummary:
        """把运行时会话状态映射为 API 层摘要对象。"""
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

    def _build_default_investigator_card(
        self,
        player_id: str,
        *,
        module_id: str,
        module: ModuleDefinition | None = None,
    ) -> InvestigatorCard:
        """构造最小可用的默认调查员卡。"""
        module_definition = module or load_module_by_id(
            module_id,
            module_root=self._module_root,
        )
        return build_investigator_card(
            name=self._build_default_investigator_name(player_id),
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
            skill_templates=self._skill_templates,
            skill_inputs=self._build_default_skill_inputs(module_definition),
        )

    def _build_default_investigator_name(self, player_id: str) -> str:
        """构造长度安全且稳定的默认姓名。"""
        prefix = "调查员-"
        max_suffix_length = 30 - len(prefix)
        if len(player_id) <= max_suffix_length:
            return f"{prefix}{player_id}"

        digest = sha1(player_id.encode("utf-8")).hexdigest()[:8]
        head_length = max_suffix_length - len(digest) - 1
        return f"{prefix}{player_id[:head_length]}-{digest}"

    def _build_default_skill_inputs(
        self,
        module: ModuleDefinition,
    ) -> list[dict[str, object]]:
        """按模组动作定义挂载最小可执行技能集。"""
        skill_inputs: dict[str, dict[str, object]] = {}
        for action in module.actions:
            check = action.check
            if check is None:
                continue

            template_key, separator, branch_key = check.skill_key.partition(":")
            template = self._skill_templates.get(template_key)
            if template is None:
                raise ValueError(
                    f"模组 {module.module_id} 引用了未知技能模板: {check.skill_key}"
                )

            skill_input: dict[str, object] = {"template_key": template_key}
            if separator:
                self._fill_branch_skill_input(
                    skill_input=skill_input,
                    template=template,
                    branch_key=branch_key,
                    skill_key=check.skill_key,
                    module_id=module.module_id,
                )
            skill_inputs[check.skill_key] = skill_input
        return [skill_inputs[key] for key in sorted(skill_inputs)]

    def _fill_branch_skill_input(
        self,
        *,
        skill_input: dict[str, object],
        template: SkillTemplate,
        branch_key: str,
        skill_key: str,
        module_id: str,
    ) -> None:
        if not template.is_branch_skill:
            raise ValueError(f"模组 {module_id} 的技能 {skill_key} 不是合法分支技能")

        skill_input["branch_key"] = branch_key
        option = next(
            (item for item in template.branch_options if item.key == branch_key),
            None,
        )
        if option is not None:
            skill_input["branch_name"] = option.name
            return
        if template.allow_custom_branch:
            skill_input["branch_name"] = branch_key
            return
        raise ValueError(f"模组 {module_id} 的技能 {skill_key} 未定义合法分支")

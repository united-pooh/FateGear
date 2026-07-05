"""NPCStatePatchProposal / 校验器 / 归约器测试。

覆盖 GROUP-5 的 TASK-007 / TASK-008 / TASK-009，
仅依赖场景侧已有模型 ``NPCSessionState`` 与 ``SessionMapState``。
"""

from __future__ import annotations

from scenario.npc_patches import (
    NPCPatchRejection,
    NPCStatePatchProposal,
    apply_npc_patches,
    validate_npc_patch,
)
from scenario.session.state import NPCSessionState, SessionMapState
from scenario.story.models import StoryState


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------

def _make_session(
    npc_id: str = "npc_1",
    module_id: str = "mod_x",
    *,
    current_turn: int = 3,
    current_scene_id: str = "",
    visible_to_player_ids: set[str] | None = None,
    characteristics: dict[str, int] | None = None,
    skills: dict[str, int] | None = None,
    last_updated_turn: int = 1,
) -> SessionMapState:
    """构造带一个 NPC 的轻量 SessionMapState。"""
    return SessionMapState(
        session_id="sess_1",
        module_id=module_id,
        current_turn=current_turn,
        story_state=_story_stub(),
        npc_states={
            npc_id: NPCSessionState(
                npc_id=npc_id,
                module_id=module_id,
                current_scene_id=current_scene_id,
                visible_to_player_ids=set(visible_to_player_ids or set()),
                characteristics=dict(characteristics or {}),
                skills=dict(skills or {}),
                last_updated_turn=last_updated_turn,
            )
        },
    )


def _story_stub() -> StoryState:
    """构造最小 StoryState 占位。"""
    return StoryState(current_stage_id="entry")


def _proposal(**overrides) -> NPCStatePatchProposal:
    """构建默认合法 proposal，由调用点覆盖任意字段。"""
    base = dict(
        npc_id="npc_1",
        path="current_scene_id",
        old_value="",
        new_value="car_4",
        reason="测试转移",
        source_event_ids=["ev_1"],
        confidence=0.95,
        producer="session_init",
    )
    base.update(overrides)
    return NPCStatePatchProposal(**base)


# ---------------------------------------------------------------------------
# TASK-007：8 字段提案
# ---------------------------------------------------------------------------

class TestProposalShape:
    def test_proposal_requires_eight_fields(self) -> None:
        """Dataclass 构造必须接受 8 个字段（7 必填 + source_event_ids 有默认值）。"""
        p = NPCStatePatchProposal(
            npc_id="npc_1",
            path="current_scene_id",
            old_value="",
            new_value="car_4",
            reason="spawn",
            source_event_ids=["ev_a"],
            confidence=0.8,
            producer="session_init",
        )
        assert p.npc_id == "npc_1"
        assert p.path == "current_scene_id"
        assert p.old_value == ""
        assert p.new_value == "car_4"
        assert p.reason == "spawn"
        assert p.source_event_ids == ["ev_a"]
        assert p.confidence == 0.8
        assert p.producer == "session_init"


# ---------------------------------------------------------------------------
# TASK-008：校验器
# ---------------------------------------------------------------------------

class TestValidator:
    def test_session_init_producer_passes(self) -> None:
        """session_init 生产者的合法提案通过校验。"""
        session = _make_session(current_scene_id="")
        p = _proposal(
            producer="session_init",
            path="current_scene_id",
            old_value="",
            new_value="car_4",
        )
        result = validate_npc_patch(session, p)
        assert result is None

    def test_rejects_world_tick_producer(self) -> None:
        """world_tick 生产者必须被拒绝，reason 列出 producer + npc_id。"""
        session = _make_session()
        p = _proposal(producer="world_tick")
        result = validate_npc_patch(session, p)
        assert isinstance(result, NPCPatchRejection)
        assert result.npc_id == "npc_1"
        assert result.producer == "world_tick"
        assert "world_tick" in result.reason
        assert "npc_1" in result.reason

    def test_rejects_forbidden_path(self) -> None:
        """受限字段（last_updated_turn, npc_id, module_id）路径应被拒绝。"""
        session = _make_session()
        for forbidden in (
            "last_updated_turn",
            "npc_id",
            "module_id",
        ):
            p = _proposal(path=forbidden)
            result = validate_npc_patch(session, p)
            assert isinstance(result, NPCPatchRejection), forbidden
            assert result.path == forbidden

    def test_old_value_concurrency_conflict(self) -> None:
        """old_value != current 时应拒绝并说明 stale。"""
        session = _make_session(current_scene_id="kitchen")
        p = _proposal(
            path="current_scene_id",
            old_value="",          # 期望为空
            new_value="garden",
        )
        result = validate_npc_patch(session, p)
        assert isinstance(result, NPCPatchRejection)
        assert "stale" in result.reason
        assert "npc_1" in result.reason


# ---------------------------------------------------------------------------
# TASK-009：归约器
# ---------------------------------------------------------------------------

class TestReducer:
    def test_reducer_applies_scene_and_updates_turn(self) -> None:
        """session_init reducer 应该写入 current_scene_id 并更新 last_updated_turn。"""
        session = _make_session(current_turn=5, current_scene_id="")
        p = _proposal(
            producer="session_init",
            path="current_scene_id",
            old_value="",
            new_value="car_4",
        )
        apply_npc_patches(session, [p])

        npc = session.npc_states["npc_1"]
        assert npc.current_scene_id == "car_4"
        assert npc.last_updated_turn == 5

    def test_visible_to_player_ids_apply_successfully(self) -> None:
        """visible_to_player_ids 写入集合。"""
        session = _make_session(current_turn=7)
        p = _proposal(
            npc_id="npc_1",
            path="visible_to_player_ids",
            old_value=set(),
            new_value={"alice", "bob"},
            reason="add visible",
        )
        # 先在 session 中匹配 old_value (set())
        apply_npc_patches(session, [p])
        npc = session.npc_states["npc_1"]
        assert npc.visible_to_player_ids == {"alice", "bob"}
        assert npc.last_updated_turn == 7

    def test_characteristics_apply_successfully(self) -> None:
        """characteristics 批量覆盖或子路径写入。"""
        session = _make_session(
            current_turn=9,
            characteristics={"STR": 50, "CON": 50},
        )
        p = _proposal(
            npc_id="npc_1",
            path="characteristics",
            old_value={"STR": 50, "CON": 50},
            new_value={"STR": 60, "CON": 55},
        )
        # 先校验 old_value 匹配
        rej = validate_npc_patch(session, p)
        assert rej is None
        apply_npc_patches(session, [p])
        npc = session.npc_states["npc_1"]
        assert npc.characteristics == {"STR": 60, "CON": 55}
        assert npc.last_updated_turn == 9

    def test_reducer_updates_last_updated_turn_even_if_field_value_unchanged(
        self,
    ) -> None:
        """只要补丁通过，就应推进 last_updated_turn。"""
        session = _make_session(current_turn=11, skills={"spot_hidden": 50})
        p = _proposal(
            path="skills",
            old_value={"spot_hidden": 50},
            new_value={"spot_hidden": 55},
        )
        apply_npc_patches(session, [p])
        assert session.npc_states["npc_1"].last_updated_turn == 11
        assert session.npc_states["npc_1"].skills["spot_hidden"] == 55

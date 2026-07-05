"""NPC 状态补丁提案、校验与归约器。

提供三块能力：

1. ``NPCStatePatchProposal`` — 8 字段补丁提案（TASK-007）。
2. ``validate_npc_patch`` — 路径白/黑名单 + 旧值并发校验 + 生产白名单
   校验（TASK-008），失败返回 ``NPCPatchRejection``。
3. ``apply_npc_patches`` — 将已接受的补丁应用在 ``SessionMapState`` 上
   （TASK-009）。本模块仅提供纯函数，调用方（GROUP-9 / TASK-015）负责在
   ``resolve_turn`` 关键区段内调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 路径约束
# ---------------------------------------------------------------------------

ALLOWED_PATCH_PATHS: frozenset[str] = frozenset(
    {"current_scene_id", "visible_to_player_ids", "characteristics", "skills"}
)

DENIED_PATCH_PATHS: frozenset[str] = frozenset(
    {"last_updated_turn", "npc_id", "module_id"}
)

PRODUCER_WHITELIST: frozenset[str] = frozenset({"session_init"})


# ---------------------------------------------------------------------------
# TASK-007：数据模型
# ---------------------------------------------------------------------------

@dataclass
class NPCStatePatchProposal:
    """单条 NPC 状态补丁提案（8 个必填字段）。"""

    npc_id: str
    path: str
    old_value: Any
    new_value: Any
    reason: str
    source_event_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    producer: str = "session_init"


@dataclass
class NPCPatchRejection:
    """校验未通过时返回的拒绝记录。"""

    npc_id: str
    path: str
    producer: str
    reason: str


# ---------------------------------------------------------------------------
# TASK-008：校验器
# ---------------------------------------------------------------------------

def _extract_root(path: str) -> str:
    """取 dotted-path 的根。

    ``"characteristics.CON"`` → ``"characteristics"``；
    ``"current_scene_id"`` → ``"current_scene_id"``。
    """
    return path.split(".")[0]


def validate_npc_patch(
    session: Any,
    proposal: NPCStatePatchProposal,
) -> NPCPatchRejection | None:
    """校验单条补丁。

    成功返回 ``None``，失败返回 ``NPCPatchRejection``（带有可读的 reason）。
    校验顺序：

    1. 生产白名单（producer）。
    2. 受限/禁止路径（denied 先于 allowed，确保拒绝语义更严格）。
    3. allowed 路径集合。
    4. 旧值乐观并发校验（old_value 必须与当前值相等）。

    ``session`` 接受任何具有 ``npc_states`` 属性（dict[str, NPCSessionState]）
    的对象；这里不强制 ``SessionMapState`` 类型以方便测试构造。
    """

    # 1) producer 白名单
    if proposal.producer not in PRODUCER_WHITELIST:
        return NPCPatchRejection(
            npc_id=proposal.npc_id,
            path=proposal.path,
            producer=proposal.producer,
            reason=(
                f"producer '{proposal.producer}' is not allowed for "
                f"npc_id '{proposal.npc_id}'; "
                f"A-phase whitelist accepts only {sorted(PRODUCER_WHITELIST)}"
            ),
        )

    root = _extract_root(proposal.path)

    # 2) 禁止路径集合（无论 other 路径是否 allowed，denied 一律拒绝）
    if root in DENIED_PATCH_PATHS:
        return NPCPatchRejection(
            npc_id=proposal.npc_id,
            path=proposal.path,
            producer=proposal.producer,
            reason=(
                f"path '{proposal.path}' root '{root}' is forbidden for "
                f"npc_id '{proposal.npc_id}'; "
                f"denied set={sorted(DENIED_PATCH_PATHS)}"
            ),
        )

    # 3) 允许路径集合
    if root not in ALLOWED_PATCH_PATHS:
        return NPCPatchRejection(
            npc_id=proposal.npc_id,
            path=proposal.path,
            producer=proposal.producer,
            reason=(
                f"path '{proposal.path}' root '{root}' is not allowed for "
                f"npc_id '{proposal.npc_id}'; "
                f"allowed set={sorted(ALLOWED_PATCH_PATHS)}"
            ),
        )

    # 4) 乐观并发：old_value 必须匹配当前
    npc = session.npc_states.get(proposal.npc_id)  # type: ignore[attr-defined]
    if npc is None:
        return NPCPatchRejection(
            npc_id=proposal.npc_id,
            path=proposal.path,
            producer=proposal.producer,
            reason=f"npc_id '{proposal.npc_id}' not found in session.npc_states",
        )

    current = getattr(npc, root, None)
    if current != proposal.old_value:
        return NPCPatchRejection(
            npc_id=proposal.npc_id,
            path=proposal.path,
            producer=proposal.producer,
            reason=(
                f"stale patch for npc_id '{proposal.npc_id}' path "
                f"'{proposal.path}': expected old_value={proposal.old_value!r} "
                f"but current={current!r}"
            ),
        )

    return None


# ---------------------------------------------------------------------------
# TASK-009：纯函数归约器
# ---------------------------------------------------------------------------

def apply_npc_patches(
    session: Any,
    accepted_patches: list[NPCStatePatchProposal],
) -> None:
    """将已接受的补丁应用到 ``session.npc_states`` 上（原地写入）。

    * 调用方已持有 ``resolve_turn`` 关键区段锁（GROUP-9）。
    * 通过后写 ``last_updated_turn = session.current_turn``。
    * 列表类型 ``visible_to_player_ids`` 的 ``new_value`` 若本身就是
      ``set/frozenset/list/tuple`` 会被存入 ``set``；其余 allowed 路径
      直接赋值。
    """
    turn = getattr(session, "current_turn", None)  # type: ignore[attr-defined]
    for patch in accepted_patches:
        npc = session.npc_states.get(patch.npc_id)  # type: ignore[attr-defined]
        if npc is None:
            continue
        root = _extract_root(patch.path)

        # 子路径（如 characteristics.CON）：嵌套写入
        if root == "characteristics" and patch.path != "characteristics":
            attr = npc.characteristics  # type: ignore[attr-defined]
            attr[patch.path.split(".", 1)[1]] = patch.new_value
        elif root == "skills" and patch.path != "skills":
            attr = npc.skills  # type: ignore[attr-defined]
            attr[patch.path.split(".", 1)[1]] = patch.new_value
        elif root == "visible_to_player_ids":
            value = patch.new_value
            if isinstance(value, (set, frozenset, list, tuple)):
                npc.visible_to_player_ids = set(value)  # type: ignore[attr-defined]
            else:
                npc.visible_to_player_ids = {value}  # type: ignore[attr-defined]
        else:
            setattr(npc, root, patch.new_value)

        # 始终推进 last_updated_turn
        if turn is not None:
            npc.last_updated_turn = turn  # type: ignore[attr-defined]

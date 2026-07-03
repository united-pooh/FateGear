# 子系统 B：NPC 态度演化 + SAN 间接耦合设计

日期：2026-07-04

状态：brainstorm spec（用户审核 → 进入 writing-plans）

依赖：子系统 A（权威双仓容器 + npc_patch_queue + resolve_turn reducer 电气接点全部就绪）。

---

## 1. 范围与定位

> **一句话定位**：在子系统 A 的权威 NPC 容器之上，建立 **玩家对 NPC 的有界态度数值层** + **SAN 损失 → 观察者态度修正的间接耦合链路**；严守"LLM 只提 proposal，运行时 guardian 校验后分发 commit" 宪法。

明确不属于本子系统（留给 C/D/E）：
- NPC 技能检定（子系统 C）
- WorldLifeTick 触发 cadence（子系统 D）
- TurnResolution 回合级 metrics / KP reward（子系统 E）
- NPC 之间关系（study doc `relationships` 字段静态数据；运行时演化不在 B）

---

## 2. 六个已锁定的设计决策

| # | 决策点 | 锁定值 | 理由 |
|---|---|---|---|
| 1 | 容器位置 | NPCSessionState 权威层新字段 `player_attitudes` | 玩家对 NPC 态度是"可被玩家真实遭遇"的权威事实；复用 A 的双仓边界，不污染 NarrativeState |
| 2 | 态度值形态 | 有界整数 `score ∈ [-100, 100]` + 5 档枚举 `AffinityTier` | 直觉化（KP 直读）、演化可预测、限幅规则自然；上慢下快梯度在恐怖叙事中合理 |
| 3 | SAN-态度耦合 | 间接耦合：SAN patch 挂入 `npc_patch_queue` → WorldLifeTick 消费时转 patch | A-phase producer gate 仍关闭；SAN 损失是间接观察（"看到疯狂" ≠ 直接读 SAN 数值） |
| 4 | Tick cadence | 事件驱动：任一玩家 SAN 异常 + NPC 与他在同场景 → 立即 patch | 比固定 tick 更紧；gating 条件在 validator 层判定 |
| 5 | Delta 幅度 | 固定函数 `delta = SAN_LOSS_COEFFICIENT × san_loss_points × severity` | 简单可预测无自由裁量；未来模组 YAML 可覆盖，本子系统默认值固定 |
| 6 | 档位限幅 | 上慢下快：`+30 分/回合 (≈+2 档位)` / `-15 分/回合 (≈-1 档位)` | 信任难建、敌意易增（克苏鲁恐怖叙事一致） |

---

## 3. 数据结构

### 3.1 NPCPlayerAttitude（权威层）

```python
from enum import Enum

class AffinityTier(str, Enum):
    HOSTILE = "hostile"       # -100 .. -60
    UNFRIENDLY = "unfriendly" # -59  .. -20
    NEUTRAL = "neutral"       # -19  ..  19
    FRIENDLY = "friendly"     #  20  ..  59
    TRUSTED = "trusted"       #  60  .. 100

_TIER_BOUNDS: dict[AffinityTier, tuple[int, int]] = {
    AffinityTier.HOSTILE:     (-100, -60),
    AffinityTier.UNFRIENDLY:  (-59,  -20),
    AffinityTier.NEUTRAL:     (-19,   19),
    AffinityTier.FRIENDLY:    (20,    59),
    AffinityTier.TRUSTED:     (60,   100),
}

class NPCPlayerAttitude(BaseModel):
    score: int = Field(default=0, ge=-100, le=100, description="玩家对 NPC 的亲和分数")
    tier: AffinityTier = Field(default=AffinityTier.NEUTRAL)

    @model_validator(mode="after")
    def sync_tier_from_score(self) -> "NPCPlayerAttitude":
        """score 变更后自动同步档位：档位由 score 决定，不可独立写入。"""
        for tier, (lo, hi) in _TIER_BOUNDS.items():
            if lo <= self.score <= hi:
                if self.tier != tier:
                    self.tier = tier
                return self
        self.tier = AffinityTier.NEUTRAL  # fallback, unreachable
        return self
```

**关键约束**：`tier` 永远由 `score` 决定，没有独立 patch 路径。`path='player_attitudes.<pid>.tier'` 在 npc_patches.py 的 DENIED_PATCH_PATHS 里。

### 3.2 NPCSessionState 扩展

```python
class NPCSessionState(BaseModel):
    ...  # 7 existing fields
    game_system: Literal["coc_7e"] = "coc_7e"  # (A 阶段按研究 docs 锁定)
    parent_attitude: dict[str, "NPCPlayerAttitude"] = Field(
        default_factory=dict,
        description="玩家 → NPC 的态度（权威层）。key 为 player_id。",
    )
```

`parent_attitude` 在 `_init_npc_states` 按初始场景配置 seed（中立或特定模组预设值）。

### 3.3 姿态初始化 seed（_extension to `_init_npc_states`）

在 `_init_npc_states` 末添加：

```python
parent_attitude = {}
for player_id in player_ids:
    seed_score = npc.default_attitude_seed if hasattr(npc, 'default_attitude_seed') else 0
    parent_attitude[player_id] = NPCPlayerAttitude(score=seed_score)
session.npc_states[npc.id].parent_attitude = parent_attitude
```

---

## 4. SAN → 态度演化链路（间接耦合）

### 4.1 SAN 损失钩子（预留挂接点）

A 阶段的 `resolve_turn` reducer flush `npc_patch_queue` 逻辑已就绪（ENGINE-001）。B 阶段只需要一个挂接函数：

```python
SAN_LOSS_COEFFICIENT: int = 2   # SAN 损失 1 点 → delta ±2 分

def queue_san_attitude_patches(
    *,
    session: SessionMapState,
    san_loss_points: int,
    target_player_id: str,
    witness_npc_ids: list[str],
    severity: float,
    reason: str,
) -> None:
    """SAN 损失后，向挂起队列追加观察者对受害玩家的态度补丁。

    - 仅 A 阶段挂起；子模 D 后 producer='san_loss' gate 才开放
    - 限幅由 apply_delta 在 guard 层实现
    """
    delta = int(SAN_LOSS_COEFFICIENT * san_loss_points * severity)
    for npc_id in witness_npc_ids:
        if npc_id not in session.npc_states:
            continue
        npc = session.npc_states[npc_id]
        current = npc.parent_attitude.get(target_player_id, NPCPlayerAttitude()).score
        capped = _apply_delta_limit(current, delta)
        proposal = NPCStatePatchProposal(
            npc_id=npc_id,
            path=f"parent_attitude.{target_player_id}.score",
            old_value=current,
            new_value=capped,
            reason=reason,
            producer="san_loss",  # 子模 D 后 gate 才开放；A 阶段仅 session_init
            confidence=0.7,  # SAN-derived 非 Keeper 提案，置信度偏低
        )
        session.npc_patch_queue.append(proposal)
```

### 4.2 Delta 限幅（上慢下快）

```python
MAX_POSITIVE_DELTA_PER_TURN: int = 30   # 上 30 分 ~ +2 档
MAX_NEGATIVE_DELTA_PER_TURN: int = -15  # 下 15 分 ~ -1 档

def _apply_delta_limit(current: int, requested_delta: int) -> int:
    if requested_delta > 0:
        actual_delta = min(requested_delta, MAX_POSITIVE_DELTA_PER_TURN)
    else:
        actual_delta = max(requested_delta, MAX_NEGATIVE_DELTA_PER_TURN)
    new_score = current + actual_delta
    return max(-100, min(100, new_score))
```

---

## 5. NPCStatePatchProposal 校验扩展（B 阶段）

A 阶段的 `validate_npc_patch` + `apply_npc_patches` 已存在。B 阶段**不允许直接改** A 阶段校验代码；B 阶段以"扩展守卫"形态叠加：

### 5.1 Parent_attitude 路径加入允许集

`allowed_additional_paths = {"parent_attitude"}`：

```python
ALLOWED_PATCH_PATHS: frozenset[str] = frozenset({
    "current_scene_id", "visible_to_player_ids", "characteristics",
    "skills", "parent_attitude",            # ← B 阶段新增
})
```

`DENIED_PATCH_PATHS` 追加：

```python
DENIED_PATCH_PATHS: frozenset[str] = frozenset({
    "last_updated_turn", "npc_id", "module_id",
    "parent_attitude",    # ← 只允许子路径 parent_attitude.<pid>.score 写
})
```

**语义澄清**：`parent_attitude` 整体写是禁止的；`parent_attitude.<pid>.score` 根路径是 `parent_attitude`（在 ALLOWED 里），嵌套 key 在 reducer 的 nested path handler 里读取 `characteristics`/`skills` 风格。

### 5.2 Cproducer gate 变更（仅预留常量，不实际开放）

```python
PHASE_A_PRODUCER_WHITELIST = frozenset({"session_init"})
PHASE_D_PRODUCER_WHITELIST = PHASE_A_PRODUCER_WHITELIST | frozenset({"san_loss", "world_tick", "npc_action"})
```

B 阶段**gate 常数不变**，A 阶段 gate 仍仅 `session_init`；`queue_san_attitude_patches` 暂不被消费者消费（queue 挂起，D 阶段 drain）。

### 5.3 子路径 reducer 扩展

添加 nested-key handler for `parent_attitude.<pid>.score`：

```python
elif root == "parent_attitude" and patch.path != "parent_attitude":
    pid = patch.path.split(".")[1]
    attr = npc.parent_attitude
    if pid not in attr:
        attr[pid] = NPCPlayerAttitude()
    attr[pid].score = int(patch.new_value)  # 触发 model_validator 同步 tier
```

### 5.4 子路径 guardian 校验

```python
def _verify_parent_attitude_path(proposal, npc) -> Optional[NPCPatchRejection]:
    parts = proposal.path.split(".")
    if len(parts) != 3 or parts[2] != "score":
        return NPCPatchRejection(..., reason="parent_attitude 只允许写到 .score 子路径")
    pid = parts[1]
    if pid not in session.player_ids_set:  #  需要 set 结构加速查找
        return NPCPatchRejection(..., reason=f"player_id {pid} 不在会话中")
    return None
```

---

## 6. 数据流（端到端）

```
现有 SAN 校验失败  [A 阶段 RuleEngine 预留]
   ↓  san_loss_points, target_pid, witness_npc_ids, severity
queue_san_attitude_patches()   [新增函数]
   ↓
session.npc_patch_queue ← 追加 producer="san_loss" proposal
   ↓  [resolve_turn 每次 drain queue，ENGINE-001 就绪]
validate_npc_patches()
   ├─ phase A gate: "san_loss" not in whitelist → rejected, enqueued to RejectedNPCPatchAudit list
   └─ phase D 后 gate 开放 → accepted path validates parent_attitude.<pid>.score 路径
   ↓
apply_npc_patches()   [reducer nested path]
   ├─ NPCPlayerAttitude.score = new_value
   └─ NPCPlayerAttitude tier 自同步 (model_validator)
   ↓
下一轮 selector 读取 parent_attitudes → 注入 KP PrivateLayer 提示
   ↓
Prompt: "乘务员(玩家 A 好感 UNFRIENDLY): A 的请求可能导致乘务员回避"
   ↓
keeper_prompt
```

---

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| SAN 损失 hook 找不到 witness NPC | 跳过，不写 proposal |
| SAN 损失 hook delta 超上限 | 取 upper/lower cap 限幅 |
| patch 路径不是 `parent_attitude.<pid>.score` | validator 拒绝，记 rejection reason |
| player_id 不在 session player_ids 子集 | validator 拒绝，记 rejection reason |
| score 越出 `[-100,100]` | model_validator clamp 或 reject |
| D 阶段 gate 未开放时 drain 到 san_loss patch | 记 rejected audit，persist，不应用 |

---

## 8. 测试策略

### 8.1 必须覆盖（top-priority）

| 测试 | 应验证 |
|---|---|
| `test_parent_attitude_init_seed` | 新建 session 按 seed=0 默认值生成 parent_attitudes |
| `test_score_change_syncs_tier` | score 从 0 改到 61 → tier 自动跳到 TRUSTED |
| `test_score_boundary_clamp` | score patch = 150 → clamp 到 100 |
| `test_san_loss_queue_hook` | SAN 损失 5 点, severity=1 → queue 追加 delta=10 (SAN_LOSS_COEFFICIENT×5) |
| `test_san_delta_positive_capped` | delta = +100 请求 → 上限 +30 分实际写入 |
| `test_san_delta_negative_capped` | delta = -100 请求 → 下限 -15 分实际写入 |
| `test_parent_attitude_score_patch_applied` | 直接经 patch 改 score=40 → tier=FRIENDLY |
| `test_path_rejects_parent_attitude_top_level` | 路径 "parent_attitude" (无子路径) → 拒绝 |
| `test_path_rejects_unknown_player_id` | parent_attitude.unknown_player.score → 拒绝 |
| `test_A_phase_gate_rejects_san_loss` | A 阶段 producer="san_loss" → queue drain 后 rejected |
| `test_phase_D_gate_accepts_san_loss` | D 阶段 gate 启用后 producer="san_loss" 通过（测 future gate switch）|

### 8.2 不需要测试（留给子模 C/D/E）

- SAN 检定引擎具体数值语义
- WorldLifeTick cadence 触发
- KP reward scores

---

## 9. 文件清单（B阶段改动范围）

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `src/scenario/npc_patches.py` | 改 | ALLOWED + DENIED 路径常量的 B 阶段 extended；nested path handler 对 parent_attitude 扩展；producer whitelist PHASE_D 常量 |
| `etc/npc/parent_attitude.py` 或 `src/scenario/npc_parent_attitude.py` | 新增 | NPCPlayerAttitude + AffinityTier 数据模型 |
| `src/scenario/runtime/engine.py` | 改 | `_init_npc_states` 追加 parent_attitude seed；新增 `queue_san_attitude_patches` 函数；当前挂起 hook 仅挂起 drain（D 阶段启用） |
| `includes/san_hook.py` 或 inbound 函数 | 新增/改 | SAN loss 钩子 caller（预留挂接点） |
| `tests/scene/test_parent_attitude.py` | 新增 | §8.1 B 阶段测试集 |

不需要改：cardNarration, cards subsystem, view, cli（ layer 虽然可能新 prompt 附加 parent_attitudes 参考，但这是模块 C/D 的事）。

---

## 10. 风险与开放问题

### 风险
- **parent_attitude 与现有 NPC 态度语义不一致**：study doc 把 `relationships` 放在 ModuleNPC 静态层（NPC ↔ NPC），B 阶段 player_attitudes 是运行时权威层（player → NPC）。两套并存需要文档化区分。
- **Tier 自动同步 vs reducer 先写 score 再跑 model_validator**：需要测试验证，reducer 的 `attr[pid].score = int(...)` 会触发 model_validator。A 阶段 NPCPlayerAttitude 是新 model，但 A 阶段的 npc_patches.py reducer 没有 NPCPlayerAttitude 感知。B 阶段扩展时**必须先让 reducer 知道如何实例化**缺失的 `<pid>` entry。
- **`npc_patch_queue` 在 phase A 会 drain 含 san_loss 提案**：A 阶段 gate 会拒绝但 enqueued 到 rejected list — 必须确认 rejected list 不会 block A 阶段正常 queue drain。

### 开放问题
- **ModuleNPC 是否新增 `default_attitude_seed` 默认值字段？** 让模组作者配置种子是对的，但不在 spec 正文强制；A 阶段可后续 optional 追加。
- **是否要为 parent_attitudes 单开一个 npc_attitude 模块？** 当前先放在 `npc_patches.py` 旁边；若 B/C/D 扩展再大，再拆独立模块。

---

## 11. 不在范围内

明确不属于本文（子系统 B）：

- NPC 技能检定 + CoC 对抗检定（子系统 C）
- WorldLifeTick cadence 触发（子系统 D）
- TurnResolution metrics + KP reward（子系统 E）
- NPC ↔ NPC 运行时关系演化 — 目前仅在静态 `relationships` 字段
- SAN 检定引擎（RuleEngine 现有 san_loss hook caller 子模 B 仅作"挂起，D 阶段触"）
- keeper prompt 的具体改写提示（子模 D 在 WorldLifeTick 完成后接过）

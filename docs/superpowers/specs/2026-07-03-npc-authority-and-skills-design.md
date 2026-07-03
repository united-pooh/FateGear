# NPC 权威边界与核心 Schema 设计（子系统 A）

日期：2026-07-03

状态：草案（brainstorm 后待实现计划）

研究基础：`docs/research/agentopia-fategear-architecture-study.md` + CoC 7e Keeper
Rulebook + D&D 5e SRD 5.1（Open5e）+ 数字层适配器（BG3/Solasta/NWN/Pillars）。

---

## 0. 范围与定位

本文是 **"NPC 权威边界与核心 Schema"**（子系统 A）的精确化设计。该子系统是
好感 / 技能检定 / WorldLifeTick / KP 奖励这四个下游子系统的公共底座。

> **一句话定位**：让 NPC 从 prompt 切片里的"纸片印象"，变成**有权威位置、权威数值、
> 权威写回通道、可被玩家真实遭遇的会话对象**；同时严守"LLM 只提 proposal、运行时
> 分发 commit"宪法，A 阶段权威 NPC 状态保持 turn 期只读直到子系统 D 接管。

### 宪法三条（下游子系统不可违反）

1. **双仓分层** — 权威事实（位置 / 可见性 / 技能 / 属性）在权威运行时层（
   `state_store` 里的会话状态）；叙事印象（态度 / 压力 / 记忆 / 口吻）在叙事层。
   同一个 key 不同时承载两种语义。
2. **LLM 永远不能直接写 session state** — 不管 agent 输出怎么样的 JSON，落到
   `npc_states` / `npc_attitudes` 之前必须经 **proposal → validator → reducer**
   链路。proposal 类型本身就标记了"我要改权威"还是"我要改叙事"。
3. **权威 NPC 状态和 turn 主状态同一事务** — 与 `player_states / flags /
   clocks / scene_instances` 一起落。turn 回滚语义对 NPC 同样生效。

### 已知的子系统依赖顺序（本文仅覆盖 A）

```
A (本文) ──── 权威容器 + 写回通道 + per-player 叙事容器
│
├── B · 好感限幅与数值化（依赖 A 的 SessionNPCState 容器）
├── C · CoC 检定引擎（依赖 A 的 npc_states.* 权威字段；A 仅加载，C 消费+D 的检定）
├── D · WorldLifeTick（依赖 A 的写回通道；第一个真正的 producer）
└── E · TurnResolution metrics + KP 奖励（依赖 A/B/C/D 的产出消费）
```

---

## 1. 权威事实层：`npc_states`

### 1.1 数据结构

在 `SessionMapState` 新增 `npc_states` 字段：

```python
class NPCSessionState(BaseModel):
    """权威运行时 NPC 状态。仅承载权威事实，不承载叙事印象。"""

    model_config = ConfigDict(validate_assignment=True)

    npc_id: str = Field(..., min_length=1, max_length=40)
    module_id: str = Field(..., min_length=1, max_length=30)
    current_scene_id: str = Field(default="", description="权威位置。空=沿用模块静态。")
    visible_to_player_ids: set[str] = Field(
        default_factory=set,
        description="对该玩家可见的玩家 ID 集。空集=沿用模块静态 visibility。",
    )
    characteristics: dict[str, int] = Field(
        default_factory=dict,
        description="CoC 8 属性 (STR/CON/SIZ/DEX/APP/INT/POW/EDU)。flat {name: int}。"
                    "A 阶段从模组 YAML 加载，C 阶段 NPCRuleEngine 消费。",
    )
    skills: dict[str, int] = Field(
        default_factory=dict,
        description="CoC 技能 flat {skill_name: percent}。A 阶段从模组 YAML 加载，"
                    "C 阶段 NPCRuleEngine 消费。",
    )
    last_updated_turn: int = Field(
        default=0, description="最近一次被 D 修改的 turn 数。A 阶段恒为 0。"
    )

    # 派生值（运行时算，不持久化；列出公式供 C 引用）
    # HP   = ceil((CON + SIZ) / 10)
    # MP   = floor(POW / 5)
    # SAN  = POW（创建时；SAN 损失见子系统 B/D）
    # DB   = STR+SIZ 查表（-2 .. +2d4）
    # Move = 8，按 DEX/SIZ/年龄调整（人类默认 8）
```

`SessionMapState` 现有代码里新增一个字段（不重写整个类）：

```python
class SessionMapState(BaseModel):
    ...  # 现有字段: story_state, global_flags, clock_values,
         #           completed_actions, triggered_clock_events,
         #           scene_instances, player_states, pending_intents, resolved_ending
    npc_states: dict[str, "NPCSessionState"] = Field(
        default_factory=dict,
        description="权威运行时 NPC 状态表，key 为 npc_id。",
    )
```

### 1.2 加载语义

A 阶段权威 npc_states **仅在会话初始化时从模组 YAML 加载一次**，turn 期只读
（运行时写入源全部留给子系统 D — 见 §3.4）。

初始化流程（在 `SceneRuntime.create_session()` 内）：

```python
def _init_npc_states(module: ModuleDefinition) -> dict[str, NPCSessionState]:
    states: dict[str, NPCSessionState] = {}
    for npc in module.narrative_context.npcs:
        # characteristics / skills 在 A 阶段可选——模组 YAML 不一定给
        characteristics = dict(getattr(npc, "characteristics", {}) or {})
        skills = dict(getattr(npc, "skills", {}) or {})
        # 位置：模组有 default_scene_id（新增字段）优先，否则激活首个场景
        default_scene = npc.default_scene_id or (
            npc.active_scene_ids[0] if npc.active_scene_ids else ""
        )
        states[npc.id] = NPCSessionState(
            npc_id=npc.id,
            module_id=module.module_id,
            current_scene_id=default_scene,
            visible_to_player_ids=set(),   # 空=沿用模块 visibility
            characteristics=characteristics,
            skills=skills,
            last_updated_turn=0,
        )
    return states
```

### 1.3 `ModuleNPC` 的字段增量

`ModuleNPC`（`src/scenario/module/models.py:80`）已有 id/name/role/public_description/
persona/speaking_style/goals/knowledge_boundary/secrets/relationships/active_scene_ids/
active_stage_ids/tags/visibility。A 阶段再增：

```python
class ModuleNPC(BaseModel):
    ...  # 现有字段均不变
    default_scene_id: str = Field(
        default="", max_length=30,
        description="会话初始化时 NPC 的权威起始场景。空=沿用 active_scene_ids[0]。",
    )
    characteristics: dict[str, int] = Field(
        default_factory=dict,
        description="CoC 8 属性。A 阶段加载进 NPCSessionState.characteristics。",
    )
    skills: dict[str, int] = Field(
        default_factory=dict,
        description="CoC 技能 flat {skill_name: percent}。"
                    "A 阶段加载进 NPCSessionState.skills。",
    )
```

**向后兼容**：`characteristics` / `skills` / `default_scene_id` 都是默认空——现有
tokoyami_subset 和其他模组的 NPC 不需要任何改动；selector 的激活逻辑也保留
对 `active_scene_ids` 的回落（见 §2）。

### 1.4 派生值的运行时语义

HP/MP/SAN/DB/Move **不存**——它们在运行时按 CoC 公式计算的：

```python
def derived_stats(state: NPCSessionState) -> dict[str, int]:
    c = state.characteristics
    con, siz, pow_ = c.get("CON", 50), c.get("SIZ", 50), c.get("POW", 50)
    return {
        "hp": -(-((con + siz) // 10)),   # ceil((CON+SIZ)/10) 的整数等价
        "mp": pow_ // 5,
        "san": pow_,
        "damage_bonus": _damage_bonus(c.get("STR", 50) + siz),  # 查表，-2..+2d4
        "move": _move_rate(c.get("DEX", 50), siz),
    }
```

函数 `derived_stats` 给 C 阶段消费，A 阶段**仅作为库函数存在**，不接入任何热路径。

---

## 2. 选择器派生：`SelectedNPCContext` 权威化

### 2.1 派生关系

`NarrativeContextSelector._select_npcs()` 现在激活判定**只读模块静态**
`active_scene_ids / active_stage_ids`。A 阶段改为：

> **权威位置优先、模块静态回落**：`current_scene_id` 非空时用权威层位置做匹配；
> 空时回落 `active_scene_ids`。stage 判定语义类似。

```python
def _select_npcs(self, *, module, session, scene_id, stage_id, include_keeper, skipped):
    selected: list[SelectedNPCContext] = []
    for npc in sorted(module.narrative_context.npcs, key=lambda item: item.id):
        runtime = session.npc_states.get(npc.id)

        # keeper 隔离
        if npc.visibility == "keeper" and not include_keeper:
            skipped[f"npc:{npc.id}"] = "keeper_only"
            continue

        # 激活判定：权威位置优先，回落静态
        if runtime and runtime.current_scene_id:
            in_scope = self._is_scene_or_stage_in_authority(
                runtime.current_scene_id, stage_id, npc
            )
        else:
            in_scope = self._npc_activation_reason(
                scene_ids=npc.active_scene_ids,
                stage_ids=npc.active_stage_ids,
                scene_id=scene_id,
                stage_id=stage_id,
            )
        if in_scope is None:
            skipped[f"npc:{npc.id}"] = "scope_not_matched"
            continue

        selected.append(SelectedNPCContext(
            npc_id=npc.id, ...,
            visibility=npc.visibility,
            selection_reason=in_scope,
        ))
    return selected
```

### 2.2 per-player 可见性过滤

现有 selector 产出的是**单份** `NarrativeContextLayer`，由 keeper 通道使用。
A 阶段新增 per-player 通道——不同玩家在同一场景看到的 NPC 集合可能不同
（`visibility_state` 已有 per-player 字典，见 `SessionPlayerState.visibility_state`）。

```python
def _selected_npc_ids_for_player(
    self, *, npc, runtime, player_id,
) -> tuple[bool, str]:
    """返回 (是否可见, reason)。"""
    if runtime and runtime.visible_to_player_ids:
        visible = player_id in runtime.visible_to_player_ids
        return (visible, "visible_to_player" if visible else "not_visible_to_player")
    if npc.visibility == "keeper":
        return (False, "keeper_only")
    return (True, "public")
```

per-player 过滤仅在 player 通道调用；keeper 通道沿用现有全量逻辑保持不变。

### 2.3 向后兼容保证

- `SelectedNPCContext` **字段集完全不改**：role/persona/speaking_style/goals/
  knowledge_boundary/secrets/visibility/selection_reason 仍从模块静态填充；
  新增的 `current_scene_id` 不加入切片（它是权威事实，不该给 prompt）。
- plan_agent / render_agent / 视图层读取 `narration.selected_npcs` 的字段行为
  100% 不变。
- 现有 `tests/scene/test_context_selector.py` 中所有断言保留——除非测试显式
  断言了"权威位置覆盖静态"（这是新语义）。

---

## 3. NPCStatePatchProposal：权威层写回通道

### 3.1 proposal 数据结构

新建类（不可复用 `NarrationPatchProposal`，原因见 brainstorm）：

```python
class NPCStatePatchProposal(BaseModel):
    """对权威 npc_states 的变更提议。与 NarrationPatchProposal 分属两个写入路径。"""

    npc_id: str = Field(..., min_length=1, max_length=40)
    path: str = Field(
        ..., min_length=1,
        description="点路径，根为 NPCSessionState 字段。允许路径："
                    "current_scene_id / visible_to_player_ids / characteristics / skills。",
    )
    old_value: Any = Field(..., description="当前 NPCSessionState[path] 的值。")
    new_value: Any = Field(..., description="提议的新值。")
    reason: str = Field(..., min_length=1, max_length=500)
    source_event_ids: list[str] = Field(
        default_factory=list,
        description="关联的 committed runtime event id。空=初始化加载。",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    producer: str = Field(
        default="session_init",
        description="proposal 来源标识：session_init / world_tick / npc_action。"
                    "A 阶段仅 session_init。",
    )
```

**和 `NarrationPatchProposal` 的关键差异**：

| | NarrationPatchProposal | NPCStatePatchProposal |
|---|---|---|
| 落点 | NarrativeState（叙事软状态，非权威） | NPCSessionState（权威运行时） |
| 事务 | 独立 narration record path | resolve_turn 主事务 |
| 生产者 | Render/LNarration agent | world_tick / npc_action (D) |
| 失败回滚 | 重试 narration | 回滚整个 turn（和 player move 同语义）|

### 3.2 validator

```python
NPC_STATE_ALLOWED_PATHS = {
    "current_scene_id",
    "visible_to_player_ids",
    "characteristics",
    "skills",
    # 不允许: npc_id / module_id / last_updated_turn — 框架字段不开放 patch
}

NPC_STATE_FORBIDDEN_PATHS = {"npc_id", "module_id", "last_updated_turn"}
```

validator 规则：

1. `npc_id` 必须在 `session.npc_states` 中存在。
2. `path` 必须在 `NPC_STATE_ALLOWED_PATHS` 内。
3. `old_value` 必须**严格等于** `session.npc_states[npc_id][path]` 的当前值
   （乐观并发校验；并发冲突时拒绝）。
4. `current_scene_id` 的 new_value 必须在模块 scene_ids 集内（防越界）。
5. `visible_to_player_ids` 的 new_value 集必须是 session.player_ids 的子集。
6. `characteristics` / `skills` 的 new_value 必须是 `dict[str, int]` 子类型；值在合理
   范围内（characteristics 默认 0-100，skills 0-100）。

失败 → `RejectedNPCStatePatch`（新类，对应 `RejectedPatchAudit`）进 audit 列表；
pass → 交给 reducer。

### 3.3 reducer 与事务

reducer 在 resolve_turn 的主事务内应用 patch：

```python
def apply_npc_state_patches(
    *,
    npc_states: dict[str, NPCStatePatchProposal],
    accepted: list[NPCStatePatchProposal],
) -> None:
    for patch in accepted:
        state = npc_states[patch.npc_id]
        if patch.path == "current_scene_id":
            state.current_scene_id = str(patch.new_value)
        elif patch.path == "visible_to_player_ids":
            state.visible_to_player_ids = set(patch.new_value)
        elif patch.path in ("characteristics", "skills"):
            setattr(state, patch.path, dict(patch.new_value))
        state.last_updated_turn = ...  # 由框架统一写，禁止 proposal 直接改
```

事务边界：和现有的 `_commit_turn_results()` 内部、在同一个 db transaction 内。
回滚语义：turn 应用失败 → 所有 patch（含 NPCStatePatch）一起回滚。

### 3.4 A 阶段的写入限制

A 阶段 `producer` 字段恒为 `"session_init"`——这是唯一允许的 producer。
validator 显式拒绝 `producer != "session_init"` 的 proposal 进 A 阶段的 resolve_turn
路径（避免 D 代码被提前调用）。错误消息：

> "NPCStatePatchProposal.producer='world_tick' is not allowed in subsystem A. "
> "Runtime NPC state writes are owned by subsystem D (World Life Tick)."

子系统 D 落地时：在 validator 处打开 `"world_tick"` / `"npc_action"` producer 的
白名单即可，schema 无需改动。

---

## 4. 叙事印象层：per-player `npc_attitudes`

### 4.1 容器收紧

`NarrativeState.npc_attitudes` 从 `dict[str, str]` 改为：

```python
class NPCAttitudes(BaseModel):
    """Per-player NPC 态度桶。向后兼容默认桶 player_id='*'。"""

    by_player: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="{npc_id: {player_id: attitude_text}}。"
                    "player_id='*' 是默认桶，向后兼容现有 patch path。",
    )
```

变更点：
- 顶层 key 仍是 `npc_id`（保持现有 patch path `npc_attitudes.<npc_id>.<player_id>`
  兼容）。
- 二级 key 是 `player_id`，二级 value 是 attitude 文本。
- 读取 fallback：`attitudes[npc_id].get(player_id) ?? attitudes[npc_id].get("*")`。

### 4.2 向后兼容层

```python
class NarrativeState(BaseModel):
    ...
    npc_attitudes = Field(
        default_factory=NPCAttitudes,
        description="Per-player NPC attitude notes keyed by npc_id then player_id.",
    )

    def get_npc_attitude(self, npc_id: str, player_id: str) -> str:
        bucket = self.npc_attitudes.by_player.get(npc_id, {})
        return bucket.get(player_id) or bucket.get("*", "")
```

现有 patch path `npc_attitudes.attendant`（单桶）→ 自动映射为
`npc_attitudes.attendant.*`（默认桶），旧测试无需修改。

新 per-player patch path：`npc_attitudes.attendant.p001` → 直接命中。

---

## 5. prompt 注入层：新增权威字段接口

### 5.1 plan_agent / render_agent 消费变更

**A 阶段现有 behavior 不变**：plan_agent / render_agent 继续读
`narration.selected_npcs`（字段集不变）。权威 npc_states 不在 prompt 切片里出现。

**新增消费入口**（给子系统 C/D 预留）：

```python
# 现有 prompt 里新增一段"权威 NPC 事实"给 KP 私有层
# 注意：仅在 keep_private=True（keeper 通道）时注入，且不进入 LLM prompt 文本内容
def build_npc_facts(npc_states: dict[str, NPCSessionState]) -> dict[str, dict]:
    return {
        npc_id: {
            "current_scene_id": s.current_scene_id,
            "characteristics": s.characteristics,
            "skills": s.skills,
        }
        for npc_id, s in npc_states.items()
    }
```

A 阶段 `build_npc_facts` 作为**导出函数存在但不接入热路径**——C 阶段用来构建
检定上下文（如"NPC skill Spot Hidden 75% 参与 opposed check"），A 阶段不是强制。

---

## 6. 数据流（端到端）

```
模组 YAML 加载
  │
  ├─ ModuleNPC (含 default_scene_id / characteristics / skills)
  │
  ▼
SceneRuntime.create_session()
  │
  └─ _init_npc_states(module) → SessionMapState.npc_states
       (producer = "session_init"，一次性)

每回合 resolve_turn()
  │
  ├─ session.npc_states 被 selector 读取（权威位置优先，静态回落）
  │   → 产出 per-player selected_npcs 注入 prompt
  │
  ├─ (D 阶段才会出现 ) NPCStatePatchProposal 被提交
  │   old_value 校验 → accept / reject
  │
  └─ 与 player_states / flags / clocks / … 同一事务提交

（D 阶段预留）offline / 回合间 producer
  └─ WorldTick / NPC action → NPCStatePatchProposal
      producer = "world_tick" / "npc_action"
      🡒 复用上面同一条 validator + reducer + 事务
```

---

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| `npc_id` 在 `npc_states` 中不存在 | validator 拒绝；返回 `unknown_npc_id` |
| `path` 不在允许集 | validator 拒绝；返回 `forbidden_path` |
| `old_value` ≠ 当前值（并发冲突） | validator 拒绝；返回 `stale_patch` |
| `current_scene_id` 越界 | validator 拒绝；返回 `invalid_scene` |
| `visible_to_player_ids` 含未知玩家 | validator 拒绝；返回 `invalid_player` |
| 事务中途异常 | 整个 turn 回滚（含 NPCStatePatch），和 player move 同语义 |
| 模组 YAML 缺 characteristics / skills | 默认空 dict，不报错（向后兼容） |

所有 reject 进 `RejectedNPCStatePatch` 列表，挂在 turn resolution 的 audit 里
（与 `RejectedPatchAudit` 并行）。

---

## 8. 测试策略

### 8.1 A 阶段必须覆盖（按优先级）

1. **`test_npc_state_initialization`** — `_init_npc_states()` 从模组 YAML 正确加载
   default_scene_id / characteristics / skills；缺字段时默认空。
2. **`test_npc_state_default_scene_fallback`** — 当 `default_scene_id` 为空，回落到
   `active_scene_ids[0]`。
3. **`test_selector_uses_authoritative_location`** — selector 在
   `current_scene_id` 非空时用权威位置，禁用静态 active_scene_ids；权威为空时
   回落静态。
4. **`test_selector_per_player_visibility`** — `visible_to_player_ids` 过滤 player 通道；
   keeper 通道沿用全量。
5. **`test_npc_state_patch_proposal_validation`** — allowed/forbidden path 校验、
   old_value 并发校验、scene/player 边界校验。
6. **`test_npc_state_patch_transaction`** — proposal 与 player move 同事务提交；
   事务回滚时 NPC 状态一起回滚。
7. **`test_npc_attitudes_per_player_fallback`** — per-player bucket + 默认桶 "*" fallback。
8. **`test_npc_attitudes_backwards_compat`** — 旧 patch path `npc_attitudes.attendant`
   自动映射默认桶；现有 tests/scene/test_narration_*.py 所有命中仍过。
9. **`test_producer_gate_subsystem_A`** — A 阶段拒绝 `producer != "session_init"` 的
   proposal；给出明确错误消息。
10. **`test_derived_stats_calculation`** — HP/MP/SAN/Move/DB 的公式正确性。

### 8.2 不需要测试（留给 C/D）

- NPC 技能检定的具体数值语义（子系统 C）
- WorldLifeTick 的触发 cadence（子系统 D）
- NPC patch 在 turn 间引发的剧情迁移副作用（子系统 B/D 交界）

---

## 9. 文件清单（A 阶段改动范围）

| 文件 | 变更类型 | 变更内容 |
|---|---|---|
| `src/scenario/session/state.py` | **改** | `SessionMapState` 新增 `npc_states` 字段；新增 `NPCSessionState` 类 |
| `src/scenario/module/models.py` | **改** | `ModuleNPC` 新增 `default_scene_id / characteristics / skills` |
| `src/scenario/context/selector.py` | **改** | `_select_npcs` 加权威位置优先逻辑；新增 per-player 可见性过滤 |
| `src/scenario/context/models.py` | **改** | `SessionMapState` import；现有类不改字段 |
| `/narration/contracts.py` | **改** | `NarrativeState.npc_attitudes` → `NPCAttitudes`；`NPCAttitudes` 类新增 |
| `/narration/patches.py` | **改** | allowed paths 里加 `npc_attitudes.<id>.<player_id>` 后缀白名单 |
| `src/scenario/runtime/engine.py` | **改** | `create_session` 加 `_init_npc_states` 调用；resolve_turn 主事务挂
| NPCStatePatch reducer hook | | |
| `src/scenario/npc_patches.py` | **新增** | `NPCStatePatchProposal` + `NPCStateValidator` + `NPCStateReducer` |
| `module/tokoyami_subset/module.yaml` | **改**（可选）| 给 attendant 加 `characteristics` / `skills` 作为实测用例 |
| `tests/scene/test_npc_*.py` | **新增** | §8.1 测试集 |

不需要改（读的是 `narration.selected_npcs` 字段集或 engine.py 之外的现有 API）：

- `src/scenario/agent/models.py` — `SelectedNPCContext` / `NPCDialogue` 类均不变
- `src/scenario/agent/plan_agent.py` — 只读 selected_npcs
- `src/scenario/agent/render_agent.py` — 只读 selected_npcs
- `src/scenario/view/builders.py` — 只读 selected_npcs.npc_dialogues
- `src/scenario/cli/play.py` — 只读 selected_npcs
- `src/scenario/story/models.py` — `StoryStage.npc_presence_rules` 是纯提示文本，不动

engine.py **需要在 `create_session` 里加 `_init_npc_states` 调用**，已在 §9 标注。

---

## 10. 风险与开放问题

### 风险
- **selector 改动影响面**：selector 是 prompt 注入核心，权威位置逻辑的 bug 可能让
  NPC 从 prompt 中整体消失 → 被 §8.1 测试 3/4 覆盖，但集成测试仍需跑全套。
- **NPCAttitudes 类替换**：直接替换 `NarrativeState.npc_attitudes` 类型会触及
  `tests/scene/test_narration_*.py:21,75,96,199,109,124` 6 个命中。通过默认桶
  兼容层缓解，但仍需改这 6 个测试的断言形式（单桶 → by_player["*"]）。

### 开放问题（留到子系统 C/D/E 解决）
- NPC SAN 损失的管理现在空白——交给子系统 B（好感限幅时一并考虑 SAN 机制）。
- NPC npc_states 字段何时允许子系统 D 写——D 落地时打开 producer 白名单。
- KP reward 如何消费 npc_states 遥测——子系统 E 定义 metrics struct。

---

## 11. 不在范围内

明确不属于本文（子系统 A）：

- NPC 好感度数值化与限幅曲线（子系统 B）
- NPC 技能检定具体实现（子系统 C）
- WorldLifeTick / world tick cadence（子系统 D）
- TurnResolution metrics / KP reward 采集（子系统 E）
- clue graph / VisibilityService（文档已列为"尚无"）——由子系统 E/D 各自附带考虑

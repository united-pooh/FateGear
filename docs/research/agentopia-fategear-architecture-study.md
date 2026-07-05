# Agentopia 与 FateGear 架构融合研究

日期：2026-07-02

分支：`codex/agentopia-architecture-study`

## 研究问题

本文研究两个问题：

1. Agentopia 论文真正提供了哪些可迁移机制。
2. 这些机制如何放进 FateGear 当前架构，而不破坏 FateGear 的 COC 守密人边界。

结论先行：Agentopia 不适合被整体搬进 FateGear。更好的方向是做一个
`Agentopia-inspired NPC/World Life Layer`，把长期 NPC 记忆、离屏行动、
关系变化和世界压力作为受控建议层，放在 FateGear 的权威运行时和叙事记忆层之下。

## 一手来源与调查边界

Agentopia 来源：

- 论文：`Agentopia: Long-Term Life Simulation and Learning in Agent Societies`
- arXiv：<https://arxiv.org/abs/2606.07513>
- HTML：<https://arxiv.org/html/2606.07513v1>
- 提交日期：2026-06-05

本仓库未发现本地 Agentopia PDF，因此本文使用 arXiv HTML 作为论文一手来源。

FateGear 来源：

- `README.md`
- `src/scenario/runtime/engine.py`
- `src/scenario/runtime/rule_engine.py`
- `src/scenario/runtime/contracts.py`
- `src/scenario/agent/prompt_builder.py`
- `src/scenario/agent/models.py`
- `src/scenario/session/state.py`
- `src/scenario/story/models.py`
- `src/scenario/story/services.py`
- `src/scenario/narration/*`
- `module/tokoyami_subset/module.yaml`
- `docs/superpowers/specs/2026-06-01-kp-narration-context-design.md`
- `docs/codex/adr/2026-06-06-narration-memory-boundary.md`

## Agentopia 的架构事实

Agentopia 的研究对象不是单轮角色扮演，而是长期 agent 社会生活模拟。
论文明确把目标放在两个方向：

- 观察多年模拟中出现的社会行为。
- 用模拟经验和 life reward 训练 LLM 的社会生活能力与角色扮演能力。

核心机制如下。

### 时间结构

Agentopia 用周作为基本循环，每周包含：

1. `Plan`
2. `Contact`
3. `Activity`
4. `Review`

年末再执行 profile update、position application、life reward calculation。
论文实验是每个世界 100 个 agent 运行 10 个模拟年。

这个设计的价值不是“模拟得更细”，而是相反：它牺牲实时连续感，把时间抽象到周和年，
让长期关系、职业、技能、资产和满足感有机会发生变化。

### Agent 结构

Agentopia 的 agent 由三类内容构成：

- profile：背景、人格、才能、职位、资产等较稳定信息。
- social relationships：主要通过角色间 memory files 表示，而不是显式关系表。
- dynamic states：vitality、fulfillment、skills、position、assets。

它的上下文分三层：

- roleplay prompt：角色 persona、近期 diary、关键 memory 摘要、世界规则、role-play principles。
- stage prompt：阶段专用指令，例如 contact stage 的通信和日程规则。
- message history：当前阶段内的对话、函数调用、memory 读写结果和压缩推理。

长期记忆是 file-system-based memory。每个 agent 有：

- `general.txt`
- `characters/<who>.txt`
- `others/<name>.txt`

Agent 可以通过 `read_file`、`update_file`、`list_files` 自主管理记忆，并有 read-before-write 约束。

### Environment model

Agentopia 的 environment model 是生成式环境引擎，用于组织事件、提供环境反馈、
生成或调度 public / encounter activity，并对输出做 principle verification。

这和 FateGear 的 RuleEngine 有本质区别：Agentopia 倾向于用 LLM 替代大量硬编码环境规则；
FateGear 则把规则判定和状态提交放在运行时权威层。

### Reward 与训练

Agentopia 定义 life reward 来近似 agent well-being，主要包含：

- social standing
- subjective fulfillment
- economic status

它用高优势轨迹做 rejection sampling 训练。论文报告该训练提升模拟中的 agent well-being，
并在 CoSER 角色扮演 benchmark 上获得整体提升。

### 成本与限制

Agentopia 的规模成本极高。论文表 4 给出三世界平均成本：

- 13.7B tokens
- 567K LLM calls
- 约 186.2 wall-clock hours

论文也承认多个限制：

- turn-based LLM generation 不等于实时人类感知。
- LLM agent 仍会幻觉，例如捏造不存在的角色或地点。
- environment model 和 numeric systems 难以完全贴近真实社会。
- life reward 不保证等价于真实人类福祉。
- 所有反馈来自 AI 模型，不能证明训练结果完全对齐人类认知。

## FateGear 的当前架构事实

FateGear 当前目标在 README 开头写得很清楚：不是聊天机器人，而是可落地的 COC 守密人工具。
它面向固定模组、多玩家协作、私有信息隔离、剧情节奏控制和可审计回合处理。

### 权威边界

README 的核心原则是：

- Agent 只输出提议和叙事。
- Agent 不直接修改数据库状态。
- 真正决定状态的是 `RuleEngine`、`TransitionValidator`、`StateStore` 事务提交逻辑。

当前一轮处理被拆成：

1. `KeeperAgent(Plan)` 产出结构化计划。
2. `RuleEngine` 和 `TransitionValidator` 权威结算。
3. `KeeperAgent(Render)` 基于已提交结果产出叙事。

这正是 FateGear 和 Agentopia 最大的架构差异：FateGear 把 LLM 放在受控建议层，
而不是把 LLM 当作最终环境裁判。

### 运行时主干

`SceneRuntime.resolve_turn()` 的当前流程：

- 读取 session snapshot。
- 按玩家当前位置分组形成 scene batch。
- 可选调用 `KeeperPlanAgent`。
- 执行动态检定和 YAML 静态动作检定。
- 汇总 flag、clock、completed_actions、movement 等待提交状态。
- 可选调用批次 `KeeperRenderAgent`。
- 统一提交移动、场景、动作、flag、clock。
- 推进每回合 clock。
- 基于 runtime event 生成 `StorySignal`。
- 由 `TransitionValidator` 计算剧情迁移。
- 返回 `TurnResolution` 和完整 `event_log`。

当前有一个重要实现细节：批次 Render Agent 在该批次 outcomes 之后调用，但在全局状态统一提交、
剧情迁移计算和 ending 判断之前调用。另有 `render_narration_after_turn()` 后置 hook，
它将 committed session snapshot 交给 `NarrationPipeline`，更适合承接长期叙事记忆和未来 world tick。

### RuleEngine 的实际能力

当前 `RuleEngine` 负责：

- 判断 action 是否可执行。
- 执行 YAML action check。
- 暂存并应用 flag changes。
- 暂存并应用 clock deltas。
- 触发 clock threshold events。
- 执行 Agent 提议的 dynamic check。
- clone investigator card，隔离会话状态。

当前 runtime 中的规则效果主要是 flag 和 clock。卡牌领域模型已有 HP/SAN 的状态和修改方法，
但 `SceneRuntime` 的 action effect 还没有把 SAN/HP 作为通用 runtime effect 接入。
因此，“FateGear 当前已经真实改 SAN/HP”应改成：“人物卡领域层支持 HP/SAN，
runtime 未来可以接入，但当前模块化场景运行时主要提交 flags/clocks/movement/story”。

### PromptBuilder 与 Plan schema

`PromptBuilder` 是分层上下文编译器，不依赖 LLM。它构造：

- `SystemLayer`
- `ModuleLayer`
- `SpatialLayer`
- `HistoryLayer`
- `KeeperPrivateLayer`
- pending intent summaries

`KeeperAgentPlan` 明确只包含提议：

- `proposed_checks`
- `proposed_effects`
- `proposed_transition`
- `keeper_notes`

模型契约里写明这些字段不能直接写入 session state，必须经过 RuleEngine / TransitionValidator。

### 当前 session state

当前 `SessionMapState` 包含：

- `story_state`
- `global_flags`
- `clock_values`
- `completed_actions`
- `triggered_clock_events`
- `scene_instances`
- `player_states`
- `pending_intents`
- `resolved_ending`

`SessionPlayerState` 包含：

- `current_scene_id`
- `last_scene_id`
- `visibility_state`
- `illegal_move_risk`
- `investigator`

当前没有完整落地的 `SessionNPCState`、`ClueGraph` 或 `VisibilityService` 类型。
`StoryStage` 有 `available_clues` 和 `npc_presence_rules` 字段，
叙事层有 `clue_emphasis` 和 `npc_attitudes`，但还不是权威 clue/NPC 生命周期系统。

### Narration memory 边界

当前 narration 包已经实现了非常关键的非权威记忆边界。

`NarrativeState` 只存：

- `scene_mood`
- `npc_attitudes`
- `clue_emphasis`
- `public_observations`
- `continuity_notes`
- `style_tags`

`NarrationInputPacket` 从 committed runtime data 构造，包含 event refs、player/scene/story snapshots、
rule facts、state diffs、check results、forbidden facts、narrative state 和 retrieved memory ids。

`NarrationValidator` 会检查：

- schema
- source event ids
- cited memory ids
- forbidden fact leakage
- fact conflicts
- vector memory 是否被当作权威事实
- patch legality

`patches.py` 明确禁止 patch 指向：

- story state
- scene state
- player state
- flags
- clocks
- completed actions
- endings
- check results
- turn resolution
- runtime event
- session

ADR 也明确：narration memory 与 graph memory 只能作为 prompt context、搜索索引、
审计记录和叙事解释来源，不能改写权威 runtime 事件和状态。

## 对原对话判断的校正

用户给出的判断大方向成立：

- 两者都不是聊天机器人。
- 两者都把 LLM 放进阶段化行为循环。
- 两者都重视上下文管理。
- 两者都试图防止角色行为失真。
- 两者都要求行为后果进入某种状态。
- Agentopia 关心长期 AI 社会生活。
- FateGear 关心真人玩家参与的可控跑团主持。
- 融合方向应是 Agentopia-inspired NPC/world life layer，而不是整体迁移。

需要校正的点：

1. 当前代码没有 `src/scenario/context/selector.py`。
   FateGear 当前分层上下文主要在 `src/scenario/agent/prompt_builder.py`
   和 `src/scenario/narration/prompt.py` / `input.py`。

2. 当前代码没有完整 `SessionNPCState`、`ClueGraph`、`VisibilityService`。
   这些是合理的下一步设计目标，但不应描述为已落地现状。

3. 当前场景 runtime 没有通用 SAN/HP effect。
   `cards.domain.card` 支持 `modify_hit_point()` 和 `modify_sanity()`，
   但 `RuleEngine` 目前在场景动作层主要处理 flags、clocks、checks。

4. `tokoyami_subset` 已有强烈的最小模组结构，包括 rear threat clock、
   flags、story transitions、terminal stages，但 NPC、clue graph、离屏行动仍未建模。

## 融合原则

### 原则 1：Agentopia memory 只能启发 FateGear 的 NPC memory

Agentopia 的 `characters/<who>.txt` 很适合启发 NPC 记忆，但 FateGear 不能让 NPC 自由写世界真相。

可迁移：

- NPC 对玩家的印象。
- NPC 的恐惧、误会、信任、怀疑。
- NPC 已经公开说过什么。
- NPC 以为自己知道什么。
- NPC 的短期目标和压力。

不可迁移为自由写入：

- 关键线索是否存在。
- 线索是否被玩家获得。
- 模组真相。
- 结局条件。
- clock 值。
- 玩家位置。
- 检定结果。
- HP/SAN/资源变化。

### 原则 2：Environment model 只能做建议者

Agentopia 的 environment model 可以启发 FateGear 的 `WorldLifeTickAgent`，
但该 agent 只能输出候选 patch 或 proposal。

建议者可以提出：

- 某 NPC 离屏去了哪里。
- 某 NPC 对玩家的新态度。
- 某个场景气氛如何变化。
- 某危险时钟是否应该有叙事表现。
- 玩家卡关时是否出现非关键提示。

最终必须经过：

- schema validation
- old-value validation
- source event validation
- module boundary validation
- visibility validation
- clue fairness validation
- RuleEngine / TransitionValidator 或专门的 WorldTickValidator

### 原则 3：Life reward 应改写成 KP reward

Agentopia 的 reward 是 agent well-being，不适合直接用于 FateGear。

FateGear 更需要 KP reward：

- 玩家主动性：系统是否保留玩家选择空间。
- 线索公平性：关键结论是否能由已公开线索推理。
- 恐怖张力：clock、场景描写和失败后果是否有节奏。
- 规则一致性：检定、移动、flag、clock 是否没有被叙事改写。
- NPC 连续性：NPC 态度和语言是否稳定演化。
- 失败推进质量：失败是否带来后果，而不是死路或无事发生。
- 私密信息正确性：hidden / keeper / player scope 是否没有泄漏。
- 审计可解释性：每个状态变化是否能回到 source event。

### 原则 4：先做短周期 world tick，不做十年模拟

COC 模组的主要时间尺度是回合、场景、章节和结局，不是十年人生。

建议 cadence：

- 每回合：只做 deterministic runtime 和 narration。
- 每 N 回合或每次 story transition：运行轻量 `WorldLifeTick`。
- 每章节结束：更新 NPC 目标、压力、关系摘要。
- 模组结束后：计算 KP reward 和审计报告。

## 建议的新架构层

建议把新层命名为：

`NPC/World Life Layer`

位置如下：

```text
Player Intent
  -> SceneRuntime.resolve_turn()
  -> TurnResolution + committed SessionMapState
  -> NarrationPipeline
  -> optional WorldLifeTick
  -> validators
  -> accepted NPC/World memory patches
  -> next PromptBuilder slice
```

其中 `WorldLifeTick` 不应放进当前批次 Render Agent。更安全的第一落点是后置 hook，
因为它能读取完整 committed state、TurnResolution 和 narration record。

### 数据模型建议

第一阶段新增静态 NPC 定义：

```python
class ModuleNPC(BaseModel):
    id: str
    name: str
    public_description: str = ""
    keeper_secret: str = ""
    default_scene_id: str = ""
    agenda: list[str] = []
    knowledge_boundaries: list[str] = []
```

第一阶段新增会话 NPC 状态：

```python
class SessionNPCState(BaseModel):
    npc_id: str
    current_scene_id: str = ""
    visible_to_player_ids: set[str] = set()
    surface_attitude_by_player: dict[str, str] = {}
    private_pressure: str = ""
    memory_summary: str = ""
    last_interaction_turn: int | None = None
    offscreen_goal: str = ""
```

注意：`SessionNPCState` 可以是权威 session state，但不能由 LLM 直接写入。
LLM 只能提交 `NPCStatePatchProposal`，由 validator 和 reducer 接受或拒绝。

第一阶段不建议直接新增自由 `ClueGraph`。可以先把线索分成两类：

- authoritative clue flags：由 module action / RuleEngine / TransitionValidator 管。
- narrative clue emphasis：继续由 `NarrativeState.clue_emphasis` 管。

等 authoritative clue flags 稳定后，再升级为 ClueGraph。

### Proposal schema 建议

`WorldLifeTickAgent` 输出应该类似 narration patch，而不是自由 JSON。

```python
class NPCMemoryPatchProposal(BaseModel):
    npc_id: str
    path: str
    old_value: object
    new_value: object
    reason: str
    source_event_ids: list[str]
    confidence: float
    visibility: str
```

允许路径第一阶段只开放：

- `surface_attitude_by_player.<player_id>`
- `memory_summary`
- `private_pressure`
- `offscreen_goal`

禁止路径：

- `story_state.*`
- `global_flags.*`
- `clock_values.*`
- `completed_actions.*`
- `player_states.*`
- `investigator.*`
- `resolved_ending`
- `key_clue_location`
- `module_truth`

### Validator 建议

新增 `WorldLifeTickValidator`，规则：

- `source_event_ids` 必须解析到当前或最近窗口内的 committed events。
- `old_value` 必须匹配当前 `SessionNPCState`。
- 不允许改变 authoritative roots。
- 不允许从 hidden keeper fact 生成 public memory。
- NPC 不在场时不能获得对话内容，除非有已建模的信息通道。
- key clue 不能离屏迁移，除非 module 显式声明可迁移。
- 态度变化应限幅，例如一次回合不能从 hostile 到 trusted。
- patch 被拒绝后只进入 audit，不进入 prompt memory。

## MVP 路线

### MVP 1：NPC 受控记忆层

目标：

- 增加 `ModuleNPC` 和 `SessionNPCState`。
- 从 module YAML 加载 NPC 静态定义。
- 在 PromptBuilder/NarrationInputPacket 中按当前场景注入相关 NPC 切片。
- 允许 narration patch 更新 `NarrativeState.npc_attitudes`。
- 不引入独立 NPC agent。

验收：

- NPC 态度可跨回合保持。
- NPC 记忆不会改 flags/clocks/story/player state。
- 被拒绝 patch 有 audit。

### MVP 2：WorldLifeTick 后置层

目标：

- 在 `render_narration_after_turn()` 后新增可选 world tick。
- 每 N 回合或 story transition 时运行。
- 输出 NPC memory/state proposals。
- 只提交 validator 接受的 NPC/session 或 narrative memory patch。

验收：

- NPC 可以有离屏目标和压力变化。
- 玩家看不到不该看的 NPC private pressure。
- world tick 不会触发剧情迁移或改关键线索。

### MVP 3：KP reward 与审计评分

目标：

- 从 `TurnResolution`、`KeeperNarrationRecord`、patch audits 里计算 KP reward。
- 先做离线评分，不训练模型。
- 输出每局的质量报告。

初始指标：

- rule consistency score
- privacy safety score
- clue fairness score
- npc continuity score
- tension pacing score
- player agency score
- fallback rate
- rejected patch rate

验收：

- 每个低分项能定位到 turn、event、record、patch。
- 可以人工挑选高质量回合作为将来训练 Render/Plan agent 的数据。

## 不建议做的事

1. 不要让每个 NPC 直接成为全权自治 agent。
   当前 FateGear 还缺 NPC 权威状态、可见性服务和 clue graph，过早自治会放大越权风险。

2. 不要让 environment model 直接创造 encounter 或关键线索。
   它可以建议，但 module / validator / rule engine 才能提交。

3. 不要把 Agentopia 的 life reward 原样搬过来。
   COC 模组不是 agent 求幸福，FateGear 的目标是公平、有张力、可审计的玩家体验。

4. 不要模拟十年尺度。
   FateGear 当前最需要的是章节间和回合间连续性，不是大规模社会仿真。

5. 不要把 vector memory 当 truth。
   当前 ADR 已明确 memory/graph 非权威，这条必须保留。

## 推荐下一步

如果要从研究转实现，建议先开一个 OpenSpec change，目标限定为：

`npc-world-life-layer-mvp`

范围控制：

- 新增 module NPC schema。
- 新增 session NPC state。
- 新增 NPC patch proposal/validator。
- 把 NPC 切片接入 post-resolution narration packet。
- 增加 6 到 8 个测试，证明 LLM 不能改权威状态。

先不做：

- 独立 NPC agent。
- clue graph。
- reward training。
- 长期模拟。
- 自动 PRD 级 UI。

## 总结

Agentopia 能教 FateGear 的，不是“让 LLM 更自由”，而是“怎样把长周期行为、
记忆、关系和反馈组织成阶段循环”。

FateGear 能保留并强化的，是 Agentopia 相对薄弱的部分：

- LLM 不直接掌权。
- 状态由运行时权威提交。
- 私密信息可隔离。
- 每个结果可审计。
- 模组边界可验证。

最合理的融合目标是：

一个有硬规则内核、有受控 NPC 记忆、有离屏世界压力、有玩家视图隔离、
有 KP reward 审计闭环的 LLM-KP 框架。

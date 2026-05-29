# FateGear KP Framework Research

日期：2026-05-30

## 结论先行

FateGear 当前不是普通聊天机器人项目，而是一个 **COC 7e 守密人运行时原型**：它已经具备 YAML 模组、内存会话、玩家位置、回合意图、场景分批、规则检定、flag/clock 效果、剧情状态机、事件日志、两段式 Keeper Agent 骨架。

但它还不是“可以自然跑团”的完整框架。当前可玩性主要受限于：玩家只能提交结构化 `move/action`，模组缺少 NPC/线索/氛围/手out/私密信息层，Agent 的临场提议没有完整落地通道，玩家视图/Keeper 面板/持久化日志/NPC 状态都还没闭环。

下一步最值得做的不是先上大前端，也不是先换数据库，而是补齐：

1. 自然语言玩家输入到结构化意图的 `IntentNormalizer`
2. 玩家可见视图与私密信息隔离的 `VisibilityService`
3. `ModuleClue`、`ModuleNPC`、`AtmosphereProfile`、`PacingProfile`
4. public/private/keeper 三层叙事包 `NarrationPacket`
5. 可审计持久化 `StateStore`
6. 节奏导演 `PaceDirector`

这样 FateGear 会从“工程上能结算回合”变成“玩家真的能坐下来玩一小段模组”。

## 研究依据

本报告同时使用三类证据：

- 当前工作区源码与测试：`README.md`、`src/`、`module/`、`tests/`
- 本地验证：`pytest -q`，结果为 `119 passed, 3 skipped`
- 公开规则/主持资料：
  - Chaosium 官方 CoC Wiki: [What is Call of Cthulhu](https://cthulhuwiki.chaosium.com/rules/)
  - Chaosium 官方规则页: [The Game System](https://cthulhuwiki.chaosium.com/rules/game-system.html)
  - Chaosium Starter Set 商品页: [Call of Cthulhu Starter Set PDF](https://www.chaosium.com/call-of-cthulhu-starter-set-pdf/)
  - Chaosium Style Guide: [Call of Cthulhu Style Guide](https://www.chaosium.com/call-of-cthulhu-style-guide/)
  - The Alexandrian: [Three Clue Rule](https://thealexandrian.net/wordpress/1101/roleplaying-games/three-clue-rule-part-3-the-three-clue-rule)
  - The Alexandrian: [Don't Prep Plots](https://thealexandrian.net/wordpress/4147/roleplaying-games/dont-prep-plots)
  - The Alexandrian: [The Secret Life of Nodes](https://thealexandrian.net/wordpress/45263/roleplaying-games/the-secret-life-of-nodes)

## 这个项目是什么

项目定位写在 `README.md`：FateGear 目标是 COC 守密人工具，面向固定模组、多玩家协作、私有信息隔离、剧情节奏控制和可审计回合处理流程。

当前源码落地的是一个 Python 后端 MVP：

- `main.py`：`aiohttp` HTTP 服务入口，暴露建团、加入、提交意图、结算回合等接口。
- `src/scenario/api.py`：`ScenarioService`，把 HTTP 层请求映射到运行时。
- `src/scenario/runtime/engine.py`：`SceneRuntime`，目前最核心的编排器。
- `src/scenario/runtime/rule_engine.py`：`RuleEngine`，处理动作条件、技能检定、flag/clock 效果。
- `src/scenario/module/models.py`：YAML 模组静态结构。
- `src/scenario/story/services.py`：剧情迁移校验与状态更新。
- `src/scenario/agent/*`：两段式 Keeper Agent 契约与 OpenAI/DeepSeek 兼容调用。
- `src/cards/*`：COC 调查员卡、属性、技能、派生数值、种子数据。

项目里已有两个最小模组：

- `module/generic_mvp/module.yaml`：通用测试模组，验证找钥匙、解锁、启动机器、逃离。
- `module/tokoyami_subset/module.yaml`：《常暗之厢》最小验证模组，验证列车场景、回合威胁时钟、好坏结局。

## 什么是跑团

跑团是桌面角色扮演游戏的一种中文说法。玩家扮演角色，在主持人描述的虚构世界里做选择；主持人描述环境、扮演 NPC、裁定规则、推进后果。Chaosium 官方 CoC Wiki 的说法里，玩家扮演调查员，Keeper 负责主持并呈现情节和场景，骰子与规则用于判定行动成败。

对工程系统来说，跑团不是“聊天”，而是一个循环：

1. KP 描述场景和压力。
2. 玩家声明角色行动。
3. KP 判断行动是否成立、是否需要检定。
4. 规则层掷骰并决定结果。
5. 状态层更新位置、线索、NPC、伤害、时间、剧情阶段。
6. KP 叙事层把已提交结果讲给玩家。
7. 新局势产生，进入下一轮。

FateGear 已经实现了这个循环的硬骨架，但玩家输入和叙事体验还不自然。

## 什么是 KP

KP 是 Call of Cthulhu 里的 Keeper，官方风格要求也建议使用 `Keeper` 而不是泛称 GM。KP 的职责是：

- 选择或准备模组。
- 维护世界真相、线索、NPC 动机和危险时间线。
- 向玩家描述当前可感知信息。
- 判断玩家行动是否可行。
- 判断是否需要检定、使用什么技能、难度是多少。
- 扮演 NPC，但不替玩家做选择。
- 维护节奏、恐怖氛围、公平性和玩家边界。
- 在玩家偏离预设时维护世界逻辑，而不是强行把玩家拉回固定剧情。

在 LLM 框架里，KP 不应是一个单体模型。更稳的拆法是：

- `IntentNormalizer`：理解玩家自然语言。
- `RulesJudge` / `RuleEngine`：权威裁定。
- `ClueManager`：管理线索获取、误解、遗漏和迁移。
- `NPCController`：控制 NPC 状态、知识边界、态度和离屏行动。
- `PaceDirector`：管理时间压力、停滞、转场和危险升级。
- `Narrator`：基于已提交结果生成氛围化叙事。
- `VisibilityService`：控制 public/private/keeper 三层信息。

## Player 的功能是什么

玩家不是调用 API 的用户而已，玩家在跑团里承担的是“调查员行动源”：

- 按角色视角提出行动、提问、探索、社交、战斗、逃跑或等待。
- 根据已经获得的信息形成假设并选择路线。
- 接受骰子后果，但可以说明推动检定、补充方法或改变目标。
- 维护角色知道/玩家知道的边界。
- 参与群体协作，避免破坏其他玩家体验。

FateGear 当前的 player 功能是：

- `SessionPlayerState` 记录 `player_id`、当前场景、上个场景、可见性字典、调查员卡。
- `MoveIntent` 和 `ActionIntent` 支持移动和执行预定义动作。
- `ScenarioService` 支持建团、加入会话、提交意图和查询摘要。
- API 会按模组动作自动为默认调查员卡挂载必要技能。

缺口是：玩家还不能自然输入“我蹲下来检查座椅底下有没有血迹”，只能提交 `{ "type": "action", "action_id": "..." }` 这种结构化动作。

## KP 如何主持游戏

可执行的主持循环可以这样建模：

1. `FrameScene`：给地点、人物、可见线索、危险感和即时问题。
2. `AskIntent`：询问玩家想做什么。
3. `NormalizeIntent`：把自然语言归一成移动、调查、观察、交谈、使用物品、战斗、等待等。
4. `DecideRoll`：只有存在不确定性、压力和失败后果时才检定。
5. `SetStakes`：在骰子前确定成功/失败意味着什么。
6. `ResolveRules`：掷骰，比较难度，计算效果。
7. `CommitState`：提交位置、flag、clock、线索、NPC、伤害、SAN、日志。
8. `RenderNarration`：只读已提交结果，生成公共叙事、私密线索、Keeper 提示。
9. `AdvancePacing`：检查停滞、威胁时钟、结局条件、转场条件。

FateGear 的 `SceneRuntime.resolve_turn()` 已经接近这个结构：按场景分批，尝试 Plan Agent，执行规则，提交效果，调用 Render Agent，再推进时钟和剧情状态机。

当前最重要的偏差是：自然语言输入、线索/NPC/可见性、PaceDirector 还没有形成第一等概念。

## 模组是如何写的

一个适合 LLM KP 跑的模组，不应该只是线性小说，也不应该只是场景流程图。它应该是“可运行的调查环境”：

- `Premise`：玩家看到的事件表象。
- `Truth`：真正发生了什么。
- `Hooks`：调查员为什么卷入。
- `Timeline`：玩家不介入时，事件如何恶化。
- `Scenes/Locations`：地点、描述、出口、危险、线索、NPC。
- `Clues`：线索正文、来源、指向、公开/私密、是否核心。
- `NPCs`：公开身份、秘密、动机、知道什么、隐瞒什么、态度、下一步行动。
- `Threats`：怪物、邪教徒、灾变、倒计时、精神污染。
- `Checks`：可能触发的技能检定、SAN、伤害、对抗、推动检定。
- `Handouts`：信件、报纸、地图、录音、照片等玩家材料。
- `Clocks`：仪式完成、追兵接近、列车危险、NPC 逃离等。
- `Endings`：成功、部分成功、失败、代价结局。
- `KeeperNotes`：节奏建议、替代路线、玩家卡住时的提示。

The Alexandrian 的建议对这个项目很重要：不要准备固定剧情，而要准备情境；关键结论至少给多个线索路径；节点式模组适合调查类游戏。

FateGear 当前 YAML 已经有：

- `scenes`
- `links`
- `actions`
- `checks`
- `effects_on_success/failure`
- `clocks`
- `story_stages`
- `story_transitions`
- `endings`

但还缺：

- `clues`
- `npcs`
- `handouts`
- `atmosphere`
- `pacing`
- `private_notes`
- `fail_forward`
- `alternate_routes`
- `scene_entry_text` / `revisit_text` / `escalated_text`

## KP 如何按照模组推进游戏

KP 按模组推进，不是照着段落读，而是维护几张表：

- `TruthState`：世界真相不变。
- `ClueGraph`：玩家已经发现、遗漏、误解、尚未触发的线索。
- `SceneGraph`：玩家能去哪里，当前在哪里。
- `NPCState`：NPC 在哪里、知道什么、想要什么、下一步做什么。
- `WorldClock`：玩家不行动时，危险如何前进。
- `StoryStage`：当前大阶段和合法迁移。

FateGear 现在做得较好的部分是 `SceneGraph`、`StoryStage`、`WorldClock` 的最小版：场景移动通过 `SceneMovementRules` 和模组 `links` 判断；剧情迁移通过 `TransitionValidator` 判断；时钟通过 `ModuleClock` 和 `RuleEngine.trigger_clock_events()` 触发。

但它目前缺少真正的 `ClueGraph` 和 `NPCState`，因此还无法稳定实现“玩家没搜到关键地点时，把必要线索迁移到合理的新场景”、“NPC 根据自己知道的事情回应而不全知”、“玩家误解线索时给自然提醒”。

## KP 如何管理 player 的行为

KP 管理玩家行为，不是限制玩家，而是把自由行动翻译成公平后果：

- 合理行动：允许，并设定代价或难度。
- 不清楚的行动：追问目标、方法、风险承受。
- 越权行动：说明世界内限制。
- 破坏合作的行为：先做桌外确认，再决定是否淡出、改写或拒绝。
- 独行动作：控制聚光灯，避免一个玩家占用过长时间。
- 卡关：提供环境变化、NPC 提示、额外线索或危险推进。

FateGear 目前只能管理“结构化合法性”：

- 同一玩家同一回合只能提交一次意图。
- 会话进入结局后不能继续提交。
- 加入玩家只能在第 1 回合且无待结算意图时进行。
- 动作必须存在于模组，移动目标必须是已有场景。
- 动作必须在当前场景、当前阶段、满足 conditions 且未被 once 消耗。

还缺“玩家体验管理”：

- 自然语言澄清。
- 无效输入的友好追问。
- 聚光灯管理。
- 安全边界。
- 玩家意图冲突处理。
- 玩家之间私聊/公开行动的边界。

## KP 如何处理 NPC

TRPG 中 NPC 不是按钮，而是有目标、知识边界和行动资源的人。重要 NPC 至少应记录：

- `public_face`
- `private_goal`
- `knows`
- `lies`
- `attitude_to_players`
- `current_scene_id`
- `current_emotion`
- `relationship_map`
- `revealed_secret_flags`
- `next_action_if_uninterrupted`
- `alive/injured/unconscious/hostile`

FateGear 当前还没有 `ModuleNPC` 或 `SessionNPCState`。代码里只有轻量占位：

- `StoryStage.npc_presence_rules`
- `KeeperPrivateLayer.npc_hidden_states`
- `NPCDialogue`

这意味着当前 Render Agent 理论上能输出 NPC 台词，但没有权威 NPC 状态约束它不越界、不遗忘、不瞬移、不泄漏秘密。

## 模组如何把控时间/轮数

COC 的时间不是只有战斗轮。至少有四层：

- 叙事时间：几分钟、几小时、几天，适合调查、旅行、研究。
- 场景时间：一场谈话、一次搜索、一次潜入。
- 战斗轮：每个角色做一个关键动作，通常按 DEX 处理。
- Downtime：治疗、学习、阅读神秘书籍、恢复关系。

FateGear 当前有一个全局 `current_turn` 和 `ModuleClock`：

- `SessionMapState.current_turn` 记录当前回合。
- `ModuleClock.step_per_turn` 支持每回合自动推进。
- `threshold_events` 支持达到阈值后应用效果。
- `tokoyami_subset` 的 `rear_threat` 每回合推进，并在阈值触发坏结局路线。

缺口：

- 没有战斗轮/DEX 顺序。
- 没有叙事时间单位，比如 `date_time`、`elapsed_minutes`。
- 没有场景停留时间、搜索耗时、旅行耗时。
- 没有 `PacingState` 判断玩家卡住或节奏过慢。
- 没有多个并行时钟的展示和 Keeper 操作界面。

## 角色技能是如何生效的

COC 7e 的核心检定是百分骰下掷：普通成功需要 `roll <= skill`，困难成功看一半，极难成功看五分之一。Chaosium 官方规则页明确描述了 D100、普通/困难/极难成功、对抗检定、奖励/惩罚骰、Luck roll。

FateGear 当前实现如下：

- `cards.domain.skills` 定义技能模板、分支技能和调查员技能。
- `cards.domain.build` 能从输入构造调查员卡。
- `ScenarioService._build_default_skill_inputs()` 会扫描模组动作的 `check.skill_key`，给默认调查员挂载对应技能。
- `RuleEngine.resolve_action_check()` 读取当前玩家的 `investigator.skills[skill_key]`。
- 难度通过 `ModuleActionCheck.difficulty` 设置为 `regular/hard/extreme`。
- 成功后应用 `effects_on_success`，失败后应用 `effects_on_failure`。

缺口：

- 技能提升和成长没有接入。
- pushed roll 没有接入。
- bonus/penalty dice 没有接入。
- Luck/SAN/对抗检定/战斗/伤害还没有完整运行时规则。
- 静态动作检定没有返回完整 `roll_value` 与 `success_level` 日志；动态 proposed check 有。

## 技能是如何使用的

玩家说出行动后，KP 应判断：

- 这是否需要技能？
- 技能是什么？
- 难度是什么？
- 成功和失败的 stakes 是什么？
- 是否可以用替代技能？
- 是否允许 pushed roll？
- 是否触发 SAN、伤害、时钟、NPC 态度变化？

FateGear 当前的技能使用路径是：

1. 模组作者在 YAML 的 action 上写 `check.skill_key` 和 `difficulty`。
2. 玩家提交 `ActionIntent(action_id)`。
3. `RuleEngine.can_execute_action()` 判断场景、阶段、once、conditions。
4. `RuleEngine.resolve_action_check()` 掷 D100 并比较阈值。
5. 成功/失败效果进入暂存集合。
6. 回合结算末尾统一提交 flag/clock/story transition。

如果配置了 Plan Agent，则 Agent 可提出 `ProposedCheck`，运行时会先执行动态检定。但目前 `proposed_difficulty` 只用于叙事参考，不改变阈值；`proposed_effects` 和 `proposed_transition` 没有形成完整白名单落地流程。

## 骰子是如何判断的

当前规则层：

- 默认 `roll_provider` 是 `randint(1, 100)`。
- 测试可注入固定骰值，保证可回归。
- 静态 action check 按难度计算阈值：
  - regular: `skill`
  - hard: `skill // 2`
  - extreme: `skill // 5`
- 动态 proposed check 会返回成功等级：
  - `extreme`
  - `hard`
  - `regular`
  - `fail`
- 掷骰值若不在 `1..100` 会抛错。

缺口：

- 没有统一 `DiceRoll` 模型。
- 没有 `dice_roll_log`。
- 静态检定没有把 roll 和 success_level 写入 `TurnResolution`。
- 没有 critical/fumble、bonus/penalty dice、opposed roll、damage dice、SAN loss dice。
- 没有“骰子前 stakes 明示”和“失败推进”机制。

## KP 如何营造氛围感

CoC 氛围不是堆形容词，而是信息控制和节奏控制：

- 先写具体感官，再给解释：气味、湿度、光线、触感、声音。
- 日常安全感与不合理细节形成反差。
- 逐步升级：异常痕迹 -> 证据矛盾 -> 人类恶意 -> 神话真相。
- 不过早解释怪物和宇宙观。
- 调查场景要清楚，恐怖时刻可以保留空白。
- 失败不要只说失败，要带来代价、误导、时间推进或危险暴露。
- 保持玩家边界：恐怖是体验，不是强迫不适。

FateGear 当前有氛围雏形：

- `ModuleScene.description`
- `StoryStage.description`
- `PromptBuilder` 的 COC 规则摘要与 Keeper role hint
- `KeeperRenderAgent` 的系统提示中要求压抑、未知、不破坏第四堵墙

但还缺：

- 模组级 `AtmosphereProfile`
- 场景首次进入/再次进入/危险升级的不同描述
- 感官素材表
- 禁止提前揭示项
- 节奏标签
- 恐怖升级规则
- 玩家边界/安全工具
- 叙事质量测试或 snapshot

## 当前项目已经解决了什么

已经解决或基本解决：

- 项目方向：不是自由聊天，而是可审计的 COC 守密人工具。
- YAML 模组加载与语义校验。
- 场景、连线、动作、flag、clock、剧情阶段、剧情迁移、结局的最小表达。
- 内存会话创建、加入、当前回合、玩家位置和人物卡绑定。
- 玩家结构化意图提交。
- 按玩家当前场景分批结算。
- 场景移动校验。
- 动作条件校验。
- d100 技能检定。
- 成功/失败效果应用。
- 全局时钟与阈值事件。
- 剧情状态机合法迁移。
- 事件日志返回。
- HTTP API 最小闭环。
- 两段式 Agent 骨架：Plan 提议，Render 叙事。
- LLM 失败时 fallback 的基本思路。
- DeepSeek/OpenAI compatible 配置兼容。
- 角色卡、属性、派生值、技能模板和分支技能。
- 测试覆盖足够支撑当前 MVP：`119 passed, 3 skipped`。

## 当前不足

关键不足按影响排序：

1. 玩家体验不像跑团：只能提交结构化 intent，不能自然语言行动。
2. 模组表达力不足：缺线索、NPC、手out、氛围、节奏、私密信息。
3. NPC 没有状态：无法稳定控制 NPC 位置、知识、动机、关系和记忆。
4. 可见性没有闭环：`visibility_state` 存在，但没有玩家视图接口和私密消息分发。
5. Agent 提议未完整落地：`proposed_effects` / `proposed_transition` 还缺白名单校验与 EffectApplier。
6. Render 输入太薄：只看本批次效果摘要，缺 NPC/线索/场景氛围/玩家历史。
7. 时间系统粗：只有全局 turn 和 clock，缺叙事时间、战斗轮、耗时、场景停滞。
8. 骰子系统不完整：缺 DiceRoll、dice log、bonus/penalty、pushed roll、Luck、SAN、对抗、战斗。
9. 审计不持久：内存会话可测但不可恢复，日志只随 TurnResolution 返回。
10. Keeper 工具缺失：没有 keeper-view、回放、调试面板。
11. 模组创作缺 schema/指南：作者不知道如何把真实模组转成可跑数据。

## 可升级方向

### P0：让玩家能自然玩一轮

新增 `scenario.intent`：

```python
class RawPlayerInput(BaseModel):
    session_id: str
    player_id: str
    text: str


class NormalizedIntent(BaseModel):
    player_id: str
    raw_text: str
    kind: Literal["move", "action", "observe", "talk", "use_item", "wait", "unknown"]
    scene_id: str
    target_scene_id: str | None = None
    action_id: str | None = None
    npc_id: str | None = None
    freeform_goal: str = ""
    confidence: float
    needs_clarification: bool = False
    clarification_question: str = ""
```

同时给 `ModuleAction` 增加：

- `description`
- `aliases`
- `expected_inputs`
- `success_stakes`
- `failure_stakes`
- `fail_forward`

### P1：补真正的模组信息层

新增：

```python
class ModuleClue(BaseModel):
    id: str
    title: str
    text: str
    source_scene_ids: list[str]
    related_action_ids: list[str] = []
    points_to: list[str] = []
    visibility: Literal["public", "private", "keeper"] = "public"
    is_core: bool = False


class ModuleNPC(BaseModel):
    id: str
    name: str
    public_face: str
    private_goal: str
    knows: list[str]
    secrets: list[str]
    default_scene_id: str


class AtmosphereProfile(BaseModel):
    tone: str
    sensory_palette: list[str]
    escalation_rules: list[str]
    forbidden_reveals: list[str]
```

### P2：补状态和视图层

新增：

- `SessionClueState`
- `SessionNPCState`
- `PacingState`
- `PlayerViewBuilder`
- `KeeperViewBuilder`
- `NarrationPacket`

建议叙事包：

```python
class NarrationPacket(BaseModel):
    turn_no: int
    scene_id: str
    public_text: str
    private_messages: dict[str, list[str]]
    revealed_clue_ids: list[str]
    npc_dialogues: list[NPCDialogue]
    keeper_notes: list[str]
    mood_tags: list[str]
```

### P3：补规则完整度

优先加：

- `DiceRoll`
- `CheckRequest`
- `CheckResult`
- `dice_roll_log`
- 静态检定也返回 roll 和 success_level
- pushed roll
- bonus/penalty dice
- Luck roll
- SAN roll
- opposed roll

之后再加：

- 战斗轮
- 伤害骰
- 护甲
- 重伤/濒死
- 疯狂发作

### P4：补持久化和审计

先做 SQLite/JSONL 即可，不必马上 PostgreSQL：

- `sessions`
- `turns`
- `player_intents`
- `event_log`
- `dice_roll_log`
- `agent_plan_log`
- `narration_log`
- `private_message_log`

### P5：补 KP 面板与调试能力

API：

- `GET /sessions/{session_id}/view?player_id=...`
- `GET /sessions/{session_id}/keeper-view`
- `GET /sessions/{session_id}/turns/{turn_no}`
- `GET /sessions/{session_id}/event-log`

Keeper 面板至少展示：

- 当前阶段
- 玩家位置
- NPC 状态
- 已发现/未发现线索
- 活跃时钟
- 可触发迁移
- 最近事件
- Agent 提议与被拒原因

## 推荐实施顺序

1. `IntentNormalizer`：玩家自然语言进入系统。
2. `NarrationPacket`：把 public/private/keeper 输出规范化。
3. `PlayerViewBuilder`：保证玩家只看到该看的内容。
4. `ModuleClue` 与 `ClueDiscoveryState`：让调查游戏真正成立。
5. `ModuleNPC` 与 `SessionNPCState`：让 NPC 可控、可记忆、不会全知。
6. `AtmosphereProfile` 与 PromptBuilder 扩展：让叙事贴合模组。
7. `DiceRoll/CheckResult` 与骰子日志：让检定可审计。
8. `StateStore`：让会话可恢复、可回放。
9. `PaceDirector`：管理卡关、停滞和危险升级。
10. Keeper 面板：服务调试和主持体验。

## 最终判断

FateGear 当前已经把“LLM 不能直接改状态、规则先落定、叙事后生成、模组状态可审计”这几条关键方向选对了。它解决的是 **跑团框架里最容易失控的硬边界问题**。

它还没解决的是 **玩家感受到的那部分跑团**：自然输入、线索网络、NPC 情绪与知识边界、私有信息、氛围节奏、骰子前的 stakes、失败推进、Keeper 调试工具。

因此最合理的产品路线是：

> 保留当前硬状态运行时，把下一阶段定义为“Playable Keeper Experience Layer”：自然语言意图、可见视图、线索/NPC/氛围数据、分层叙事包和可审计骰子日志。

只要这一层补上，FateGear 就会从“能跑通回合的后端原型”，变成“可以让玩家进入模组、让大模型扮演 KP、并由规则层兜住状态一致性”的可玩框架。

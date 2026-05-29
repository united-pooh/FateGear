# Changelog

## 2026-05-30

### Added
- 新增只读 NarrativeContext v0：模组可声明 NPC 人设卡、世界书条目、氛围配置、KP 文风控制和安全边界。
- 新增确定性 `NarrativeContextSelector`，按场景、阶段、动作、关键词、NPC、优先级和预算选择本轮叙事上下文。
- Plan/Render Agent 输入增加 `narrative` 层，并在 prompt 中注入上下文；不改变 `KeeperAgentPlan` / `KeeperNarration` 输出 schema。
- 模组 loader 接入人物卡技能模板注册表，加载期拒绝未知技能模板、缺失分支后缀和非法分支技能。
- 新增玩家/守密人视图投影：`PlayerTurnView`、`KeeperTurnView`、`PlayerSessionView`、`KeeperSessionView`。
- 新增确定性 `IntentNormalizer`，支持自然语言移动/动作匹配、动作别名和澄清问题。
- `ModuleAction` 新增 `description`、`aliases`、`expected_inputs`、`stakes`、`fail_forward_hint` 作者字段。
- HTTP 新增 `GET /sessions/{session_id}/players/{player_id}/view` 与 `GET /sessions/{session_id}/keeper-view`。
- HTTP 新增 `POST /sessions/{session_id}/text-intents`，用于提交自然语言玩家意图。
- `tokoyami_subset` 示例模组展示常暗列车的 NPC、世界书、氛围和安全边界写法。
- 新增五轮升级审计文档：`docs/fategear-five-iteration-upgrade.md`。
- 新增 `JsonScenarioStateStore`，支持把会话快照和回合结算历史持久化到本地 JSON 并在运行时启动时恢复。

### Changed
- Render Agent 调用后移到权威状态提交之后，叙事输入现在能看到本回合最终剧情迁移、新阶段和结局。
- HTTP `POST /sessions/{session_id}/resolve` 改为返回守密人视图，避免裸返内部 `TurnResolution`。
- `SceneRuntime.resolve_turn` 增加 per-session `asyncio.Lock`、回合历史和 `expected_turn` 幂等重放；`ScenarioService.resolve_turn` 不再持有 `RLock` 跨 `await`。
- `ScenarioService` 可接收 `state_store` 创建可恢复运行时，并会为恢复会话重建稳定 owner 映射。
- 玩家/守密人回合视图兼容 JSON 往返后的叙事 dict，继续保持私密线索与 keeper-only 内容隔离。

### Tests
- loader 测试覆盖 NarrativeContext 成功加载、重复 NPC、坏世界书引用和缺失触发条件。
- loader 测试覆盖非法 action skill_key。
- selector 测试覆盖优先级排序、上下文预算裁剪和跳过原因。
- PromptBuilder 测试覆盖世界书、氛围、KP 文风和 keeper-only 条目的公开渲染隔离。
- Runtime smoke 测试覆盖 Planner 与 Narrator 都能收到选中的叙事上下文。
- Runtime smoke 测试覆盖 Narrator 能看到最终 `applied_transition_id`、`new_stage_id` 和 `resolved_ending`。
- 视图测试覆盖玩家 payload 不泄漏他人私有线索、keeper-only NPC 台词和 `keeper_hint`。
- API/HTTP 测试覆盖当前玩家视图和守密人视图。
- IntentNormalizer 测试覆盖自然语言移动、动作别名匹配和澄清路径。
- API/HTTP 测试覆盖自然语言意图提交。
- Runtime/API/HTTP 测试覆盖 expected-turn 回放和并发同回合防双提交。
- StateStore 测试覆盖会话恢复、回合历史恢复、删除清理，以及 JSON 叙事往返后的玩家视图过滤。

## 2026-03-30

### Breaking Changes
- 移除旧 `scene.*` 命名空间（`src/scene` 整包删除），不再提供兼容层。
- 统一收敛到 `scenario.*` 新框架，运行时唯一入口为 `scenario.runtime.SceneRuntime`。

### Changed
- `scenario.module` 包导出改为惰性加载，避免 `story.models -> module.__init__ -> module.models` 的循环导入。
- 运行时相关测试收集路径已打通，可直接执行 `tests/scene/test_runtime.py --collect-only`。

## 2026-03-27

### Added
- 新增 YAML 模组静态定义模型，支持 scene、link、action、clock、ending 的最小表达。
- 新增模组 loader，可从 `module/<module_id>/module.yaml` 加载并执行结构与语义校验。
- 新增内存内 `SceneRuntime`，支持创建会话、提交结构化意图、按全局回合结算、多 scene 同步与 clock 阈值触发。
- 新增两个样例模组：
  - `module/generic_mvp/module.yaml`
  - `module/tokoyami_subset/module.yaml`
- 新增 `PyYAML` 依赖。

### Tests
- 新增 loader 测试，覆盖样例模组加载、重复 scene、坏 link、坏 action.scene_id、坏 clock 引用。
- 新增 runtime 测试，覆盖会话初始化、结构化动作、受限连线、全局回合推进、多 scene 同步、clock 阈值与 happy path。
- 为 `SceneMovementRules` 新增实际可达性测试，同时保留无配置时的显式未实现行为断言。

### Known Limitations
- 运行时状态仅保存在内存中，不接数据库或 API 层。
- 只支持结构化 `action_id` / `move` 意图，不处理自然语言输入。
- `Condition` / `Effect` 仅实现 MVP 所需的最小类型集合。
- `SceneRouter` 仍保留占位职责，当前可跑通链路由 `SceneRuntime` 提供。

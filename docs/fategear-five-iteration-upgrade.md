# FateGear 五轮叙事引擎升级审计

## 外部经验转译

本轮升级参考了两类公开经验：

- CNMods 公开模组页呈现出的 KP 写作趋势：强开场身份、具体异常物、阶段性压力、敏感内容预警、以及“氛围要持续运转而不是只靠一句风格提示”。
- SillyTavern/酒馆生态的工程经验：角色卡固定人设，World Info/Lorebook 按关键词和范围动态插入，Author's Note 通过靠近输出端的位置强化风格，Data Bank/RAG 作为外部知识源补充长期记忆。

这些经验在 FateGear 中不直接复制外部文本，而是转成可验证能力：人物卡式 NPC、世界书条目、氛围/文风约束、安全边界、确定性上下文选择、以及 Prompt 注入。

## 批判审计

1. 当前输入仍是结构化 `move/action`，不是自然语言跑团输入。它能跑状态机，但还不是成熟 AI KP。
2. 私密信息隔离不足。`private_clues` 与 `visibility_state` 已有名字，但还没有完整玩家视图、守密人视图和可审计投递通道。
3. Agent 边界还不够硬。Planner 可以提议动态检定，但难度未完全落入权威规则模型，`proposed_effects` 与 `proposed_transition` 仍没有完整执行闭环。
4. `SceneRuntime.resolve_turn` 过重，承担计划、规则、效果、迁移、叙事和提交，后续 NPC、线索、持久化都会继续挤压这里。
5. 模组 schema 太薄，缺少 NPC、线索、世界书、氛围、节奏、安全提示等严肃 KP 需要的准备信息。
6. PromptBuilder 之前不是上下文引擎：`worldview_brief` 为空，动作描述为空，可用动作与可达场景没有足够上下文筛选。
7. Render 在完整提交前运行，无法可靠叙述最终迁移、时钟阈值和结局。
8. 测试目前证明 MVP 能跑，不能证明产品级 KP 能维持氛围、人设、隐私和长期一致性。

## 五轮升级计划

### 第 1 轮：只读 NarrativeContext v0

目标：先补上“人设、世界书、氛围、文风、安全边界”的模块表达与 Prompt 注入。

已落地：
- `ModuleNarrativeContext`、`ModuleNPC`、`ModuleLorebookEntry`、`ModuleAtmosphereProfile`、`ModuleKPProseControls`、`ModuleSafetyBoundary`。
- `NarrativeContextSelector`，按场景、阶段、动作、关键词、NPC、优先级与预算选择上下文。
- `AgentPlanPrompt` 与 `CommitResult` 增加只读 `narrative` 层。
- Plan/Render prompt 注入叙事上下文，但不授予任何状态修改权。
- `tokoyami_subset` 增加示例 NPC、世界书、氛围和安全边界。

验证：
- `tests/scene/test_loader.py`
- `tests/scene/test_prompt_builder.py`
- `tests/scene/test_runtime_smoke.py`

残余风险：Render 仍在完整提交前运行；本轮只解决“输入给模型的信息”，不解决最终叙事时序。

### 第 2 轮：校验与作者诊断

目标：让模组作者写错时早失败、好理解、可迁移。

已落地：
- loader 调用人物卡技能模板注册表，在加载 YAML 时校验 `action.check.skill_key`。
- 未知技能模板、分支技能缺少后缀、非法分支技能会直接抛出 `ModuleValidationError`。

应继续完成：
- 校验 action aliases、expected inputs、fail-forward 元数据。
- 增加更系统的坏 YAML fixtures。
- 输出更精确的字段路径诊断。

### 第 3 轮：上下文检索和预算硬化

目标：把世界书能力从“能选中”推进到“可审计、可调预算、可解释跳过原因”。

应继续完成：
- 继续扩展 selector 测试，覆盖关键词命中和 NPC 关联命中。
- 暴露 selection trace 给日志和调试 API。
- 给 Plan/Render 分别设置预算。

### 第 4 轮：调查连续性和 NPC/线索状态

目标：从静态提示升级到会话内的调查状态。

应继续完成：
- `SessionNPCState`、`SessionClueState`、`ClueGraph`。
- 私有线索投递与可见性隔离。
- NPC 知识边界与已揭示秘密的权威校验。
- SAN、Luck、奖励/惩罚骰、对抗检定等 COC 规则审计结构。

### 第 5 轮：产品级 KP 操作面和交付证明

目标：让守密人能运营、回放、审计一局游戏。

应继续完成：
- KeeperView / PlayerView。
- turn replay、event log、dice log、Agent log。
- 幂等 resolve 和持久化 StateStore。
- 完整 tokoyami 分支回归与 Agent 失败降级回归。

## 本轮边界

第 1 轮刻意保持只读：NarrativeContext 可以影响提示文本，但不能修改 flag、clock、动作可用性、检定结果或剧情迁移。这个边界保留了 FateGear 当前最重要的安全性：运行时规则仍由 RuleEngine 与 TransitionValidator 负责。

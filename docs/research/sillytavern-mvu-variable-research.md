# SillyTavern MVU 变量技术与作用深度研究报告

日期：2026-06-03
对象：SillyTavern 生态中的 MVU / MagVarUpdate 变量框架
范围：技术机制、运行链路、作用边界、风险、最佳实践，以及对 FateGear 的可迁移设计启发

## 摘要

SillyTavern 里的“MVU 变量”在当前社区语境里通常不是指前端架构里的 Model-View-Update，也不是 SillyTavern 官方核心文档里的一项原生功能，而是以 MagVarUpdate 为代表的一套第三方变量状态维护工作流。它依赖 Tavern Helper / JS-Slash-Runner 等扩展提供的脚本执行、变量读写、消息级数据读写和渲染能力，再通过角色卡世界书、提示词模板、正则隐藏、消息事件监听和结构化解析，把大模型每轮生成末尾附带的变量变更语句转化为 SillyTavern 聊天文件中的结构化状态。

它的核心价值可以用一句话概括：让大模型描述“状态应该如何变”，但让程序负责解析、验证、提交和展示状态。也就是说，MVU 不是“让模型记得更多”，而是把“记忆”从模型的自然语言上下文里抽出来，变成可持久化、可检查、可回放、可展示的结构化变量。早期它主要用 `_.set('路径', 旧值, 新值)` 这类近似代码的格式来更新变量；MagVarUpdate beta 分支已经扩展出 `_.add`、`_.assign`、`_.remove`、JSONPatch 方言、schema / `$meta` 约束、事件钩子、额外模型解析和 function calling 路径，说明它正在从“状态栏辅助脚本”演化成一种轻量的角色扮演状态机框架。

MVU 解决的是长篇角色扮演和类 RPG / 恋爱模拟 / 世界模拟中的一类顽固问题：角色好感度、时间、地点、库存、任务、关系、NPC 当前状态等信息，如果只放在聊天历史和自然语言总结里，会随着上下文裁剪、模型注意力漂移、重生成、隐藏楼层、长期游玩而逐渐失真。MVU 把这些信息写进每条消息的变量数据里，并让下一轮提示词读取最新 `stat_data`，从而把“上一轮真实状态”稳定地带入下一轮生成。对用户而言，它表现为“角色不会忘记 HP / 好感 / 背包 / 当天时间 / 关系进度”；对制作者而言，它提供了状态栏、事件触发、分段提示词、剧情门槛、调试面板和变量查看器的基础。

但 MVU 不是万能药。它仍然依赖模型遵守输出格式，依赖提示词把变量更新规则说明清楚，依赖扩展脚本安全可靠，依赖 schema 与事件钩子阻止模型破坏结构。它也会带来额外 token 成本、提示词复杂度、调试成本和第三方 JavaScript 执行风险。最关键的边界是：MVU 适合管理“叙事连续性状态”和“可被模型建议更新的模拟状态”，不适合把强规则游戏的权威判定完全交给模型。对于 FateGear 这样的规则驱动跑团系统，正确迁移方式不是照搬 SillyTavern 卡面里的变量提示词，而是吸收它的架构原则：LLM 产出结构化 patch，后端 reducer / validator 决定是否提交，状态变更落入事件日志，叙事记忆与权威规则状态分层。

本报告的结论是：MVU 的本质是一种“前端可配置、模型辅助、脚本归约”的状态补丁协议。它最有价值的部分不在某个具体标签或命令名，而在四个设计思想：第一，状态以嵌套 JSON 结构定义，变量本身携带更新条件；第二，模型输出的只是候选变更，不直接等同真实状态；第三，程序用解析器、schema、事件钩子和消息变量完成提交；第四，展示层读取 `display_data` / `delta_data`，而不是直接相信模型自然语言。围绕这四点建设，MVU 可以显著提高长篇互动叙事的稳定性；忽视这四点，只把它当作“让模型每轮输出一堆变量”，则容易变成高成本、低可靠的提示词负担。

## 资料来源与调查边界

本次调查采用三类资料。

第一类是 SillyTavern 官方文档。官方文档说明了 prompt 是由主提示词、角色定义、世界信息、Data Bank、总结、聊天历史、用户消息和最终指令等多种内容合成的，并说明用户可以通过 Prompt Manager 控制 Chat Completion API 的提示词构建策略。官方文档也说明了 macros / variables 的基础机制：SillyTavern 的宏可以在提示词、角色卡、世界书、Quick Replies 等字段中替换动态值，局部变量和全局变量可以通过 `{{getvar}}`、`{{setvar}}` 或简写形式读取和写入。World Info 文档说明世界书本质上是提示词管理和知识注入工具，并且强调它只能引导模型，不保证输出必然使用这些信息。Data Bank 与 Chat Vectorization 文档则说明了 SillyTavern 原生 RAG 与聊天向量化的上下文检索能力；这些能力可以改善上下文召回，但与 MVU 的“结构化状态提交”不是同一层东西。主要参考链接包括：[SillyTavern Prompts](https://docs.sillytavern.app/usage/prompts/)、[Prompt Manager](https://github.com/SillyTavern/SillyTavern-Docs/blob/main/Usage/Prompts/prompt-manager.md)、[Macros](https://docs.sillytavern.app/usage/core-concepts/macros/)、[World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)、[Data Bank](https://docs.sillytavern.app/usage/core-concepts/data-bank/)、[Chat Vectorization](https://docs.sillytavern.app/extensions/chat-vectorization/)。

第二类是 MVU 直接实现资料。主要是 [MagicalAstrogy/MagVarUpdate](https://github.com/MagicalAstrogy/MagVarUpdate) beta 分支的 README、教程、补充教程与源码。README 把 MagVarUpdate 描述为基于 Tavern Helper 的脚本，用于提供简单的基于变量的状态维护，并减少状态栏编写对模型注意力的消耗。教程解释了它为何替代早期正则变量更新方案：旧方案需要与模型输出边缘情况和正则表达式反复斗争，隐藏旧楼层会造成变量不一致，持续扫描所有楼层也会带来运行时开销。MagVarUpdate 的源码显示它在消息发送和接收事件后处理变量，在 `<UpdateVariable>` / `<JSONPatch>` 中提取命令，更新 `stat_data`、`display_data`、`delta_data`，并把结果写回消息变量。关键源码包括 `src/function/update_variables.ts`、`src/function/initvar/variable_init.ts`、`src/function/schema.ts`、`src/function/function_call.ts`、`src/variable_def.ts`。

第三类是底层扩展与社区使用案例。MagVarUpdate 依赖 [N0VI028/JS-Slash-Runner](https://github.com/N0VI028/JS-Slash-Runner)，也就是 Tavern Helper。它的 README 明确说明该扩展允许在 SillyTavern 中运行外部 JavaScript，并提示恶意脚本可能窃取 API key、聊天记录或破坏设置，因此 MVU 的安全边界必须严肃看待。社区方面，Reddit 上关于 MVU Game Maker、Artific Realm、MVU ZOD 角色卡的帖子把 MVU 描述为持久化多角色统计、GUI 状态栏、RPG / 恋爱模拟状态追踪的工作流；这些帖子不是权威文档，但能反映真实使用场景和痛点，例如依赖模型严格遵守 `<UpdateVariable>` / `<JSONPatch>` 标签，依赖 Tavern Helper 和兼容 preset，局部模型或不听指令的模型更容易更新失败。

调查边界也必须说明清楚：MVU / MagVarUpdate 不是 SillyTavern 官方核心文档中独立列出的原生模块，而是社区扩展和角色卡工作流；不同卡、不同 preset、不同分支可能使用 `MUV`、`MVU`、`MagVarUpdate`、`UpdateVariable`、`变量更新` 等混合叫法。本报告把“MVU 变量技术”定义为：以 MagVarUpdate / Tavern Helper 为主要代表，通过结构化模型输出和脚本提交来维护 SillyTavern 聊天状态变量的一组技术与实践。

## SillyTavern 的基础上下文：为什么 MVU 能成立

理解 MVU 之前，需要先理解 SillyTavern 的上下文合成方式。SillyTavern 并不是单纯把用户输入发给模型，而是把多个来源组合成 prompt。官方 Prompts 文档列举了主提示词、角色定义、用户 persona、世界信息、Data Bank 文档、总结、外部搜索、历史消息、用户消息和最终指令等部分。这意味着 SillyTavern 的“记忆”本来就是多层的：一部分是角色卡静态文本，一部分是世界书动态触发，一部分是聊天历史，一部分是变量宏或脚本生成内容，一部分是 RAG 检索结果。

Prompt Manager 进一步让用户控制这些内容以什么角色、什么顺序、什么深度插入到 Chat Completion 请求里。它的文档说明，Prompt Manager 是 prompt sent to Chat Completion model 的 backbone，列表越靠上越早发送，越靠下越接近模型生成前的尾部指令；当 prompt 设置为 In-Chat 并配置 Depth 时，它会被插入聊天历史内部某个位置。这个机制非常关键，因为 MVU 的变量规则通常需要放在模型能稳定看见、且靠近生成出口的位置；如果变量规则被放在太靠前的位置，模型可能被历史消息稀释；如果放在不合适角色或深度，模型可能不把它当作强约束。

Macros 与变量是 MVU 的另一个基础。SillyTavern 官方 Macros 文档说明宏是动态占位符，可用于 prompts、角色卡、lorebooks、Quick Replies 等地方；局部变量和全局变量有读取、设置、增加、递增、递减、删除等操作。新实验宏引擎还支持嵌套和更稳定的替换顺序。MVU 利用了这一点，把上一轮消息变量里的 `stat_data` 注入到世界书条目或提示词模板中，让模型每轮都能看到当前结构化状态。例如 MagVarUpdate 教程中的变量更新规则会把 `{{get_message_variable::stat_data}}` 放入 `<status_current_variable>` 标签，随后要求模型分析每个变量是否需要更新。

World Info 则是 MVU 提示词规则常见的承载位置。官方文档说世界书可以作为 lorebook、系统提示词管理、记忆存储、模块化角色细节和随机事件来源。它通过关键词、上下文源、插入顺序、插入位置、深度、递归等设置决定哪些内容进入 prompt。MVU 常用世界书条目存放两类东西：一是 `[InitVar]` 初始变量定义，二是 `[mvu_update]` 或类似命名的变量更新规则。因为世界书条目可以绑定到角色、persona、chat 或全局来源，MVU 变量规则既可以做成角色卡内置，也可以做成全局工作流。

Data Bank、Smart Context、Chat Vectorization 也常被用户拿来和 MVU 混谈，但它们本质不同。Data Bank 是 RAG 工具，用于把外部文档切分、向量化、检索并插入 prompt。Chat Vectorization 会把当前聊天里的历史消息向量化，在生成时把相关旧消息移动到 prompt 开头或结尾。Smart Context 旧扩展用 ChromaDB 召回超出上下文窗口的聊天消息，但官方文档已经提示它不再维护，建议考虑 Chat Vectorization。它们解决的是“哪些旧文本应该重新进入上下文”，而 MVU 解决的是“哪些状态变更应该被结构化提交”。一个是检索，一个是状态归约。两者可以互补，但不能互相替代。

因此，MVU 能成立，是因为 SillyTavern 已经提供了四个可组合能力：可控的 prompt 注入位置、可在 prompt 中动态展开变量的宏系统、可随消息保存数据的变量体系，以及可由第三方扩展在生成后运行脚本的事件/脚本环境。MagVarUpdate 把这些能力串成一个闭环。

## MVU 要解决的问题

早期 SillyTavern 角色卡常用正则、状态栏、世界书和手写变量来维持状态。比如在角色回复末尾让模型输出“好感度：50 -> 55”，再通过正则隐藏或展示。但这种方案有几个根本问题。

第一，模型输出不是稳定协议。大模型可能忘记输出、拼错字段、改变分隔符、使用中文括号、把多个变量混在自然语言里，或在长上下文中逐渐偏离格式。正则越写越复杂，但正则只能补救字符串形态，不能理解状态语义。

第二，状态依赖历史楼层。旧方案往往需要扫描一段或全部历史消息来推导最新状态。如果用户隐藏、删除、分支、重生成、切换 swipe，变量就可能不一致。MagVarUpdate 教程明确指出，旧的正则变量更新方案无法随意隐藏较早楼层，需要等完整变量更新出现后才能隐藏，否则会出错。

第三，运行时开销与调试开销高。每轮都对所有楼层做正则处理，不但性能差，而且一旦某层输出格式异常，后续状态都会被污染。用户只能靠肉眼翻聊天记录找出错点。

第四，模型注意力被状态栏消耗。状态栏既要给用户看，又要给模型读，还要指示模型如何更新。混在一起后，模型会把展示文本、真实状态、变化原因、更新规则混淆；状态栏越精美，越可能浪费 token 或引入歧义。

第五，长篇角色扮演需要“事实连续性”。RPG 和恋爱模拟中的 HP、库存、任务、时间、位置、好感、关系、NPC 是否在场、角色当前想法、世界事件等，不能只靠模型“记忆”。模型的自然语言记忆在短期内看似顺滑，但长线会产生漂移，尤其在上下文裁剪、RAG 召回不稳定、用户修改历史、模型重生成时更明显。

MVU 的方案是：每轮让模型输出一段结构化变量更新块；脚本在生成结束时解析这段块；基于上一条有效消息变量，计算新的变量状态；把新状态写到当前消息变量；下一轮 prompt 读取最新 `stat_data`。这样，状态不需要从历史文本反推，而是每层都有自己的状态快照。用户隐藏旧楼层时，只要保留最近有效变量状态，系统仍能继续。状态栏展示也可以读取 `display_data` 或 `delta_data`，而不是依赖模型写给用户看的自然语言。

从工程角度看，MVU 把“自然语言剧情”与“结构化状态”拆开了：剧情可以浪漫、含蓄、长篇；状态更新必须短、明确、可解析、可检查。这种拆分是它最重要的贡献。

## 系统组成：Tavern Helper、MagVarUpdate、世界书和正则

MagVarUpdate README 说明它基于 Tavern Helper。Tavern Helper / JS-Slash-Runner 的角色是提供 SillyTavern 默认没有暴露的脚本能力。它可以在 iframe 中运行外部 JavaScript，向脚本提供 `TavernHelper` 对象、变量读写、消息读写、事件监听、渲染 iframe、slash command 调用等能力。它的 README 同时提醒，自定义 JavaScript 代码可能带来安全风险，所以用户需要检查脚本来源和功能。

MagVarUpdate 本体通常作为角色卡局部脚本安装。教程里示例是向角色卡脚本加入一行远程 import，把 bundle.js 加载进来。脚本初始化后，会注册面板、按钮、全局对象、变量初始化、请求过滤、响应处理、清理、通知和导出事件。源码 `src/main.ts` 显示它在页面加载后检查 Tavern Helper 版本，初始化 Pinia store，并在聊天切换时重新初始化聊天级监听。

除了脚本，还需要正则。教程要求设置一个正则隐藏 `<UpdateVariable>...</UpdateVariable>`，作用范围为 AI 输出，并配置为仅格式显示和仅格式提示词；另一个正则隐藏 `<StatusPlaceHolderImpl/>`。这说明 MVU 的变量块默认存在于消息文本中，但用户正常阅读时不想看到，模型下一轮也不一定需要看到旧变量块。正则隐藏承担的是 UI 和 prompt 清理职责。

第三个组成部分是世界书变量更新规则。教程示例把当前变量状态注入 `<status_current_variable>`，随后给模型一组规则：计算时间流逝、判断是否允许剧烈更新、列出变量、按变量更新条件分析、最后用 `<UpdateVariable>` 包住 `Analysis` 和 `_.set` 命令。beta 补充教程进一步说明可使用 `_.set`、`_.assign`、`_.remove`、`_.add` 四类命令，或者使用 `<JSONPatch>` 块输出 JSON Patch 格式。

第四个组成部分是 `[InitVar]` 世界书条目。MagVarUpdate 在新聊天加载和每条消息发出前检查变量是否初始化；没有初始化时，会读取名称或注释包含 `[InitVar]` 的世界书条目。源码 `loadInitVarData` 会遍历启用的 lorebook，找到 comment 包含 `[initvar]` 的条目，剥离 `<initvar>` 或代码块外壳，用 YAML / JSON parser 解析并合并进 `stat_data`。开场白中的 `<initvar>` 或 `<UpdateVariable>` 还能覆盖初始值，用于不同开局。

第五个组成部分是消息变量写回。`handleVariablesInMessage` 会取当前消息文本，用 `getLastValidVariable` 找到上一层有效变量，执行 `updateVariables`，然后把 `initialized_lorebooks`、`stat_data`、`schema`、`display_data`、`delta_data` 写回当前消息变量。如果开启兼容选项，还会同步到聊天变量。这样每条 assistant 消息都可携带“回复完该层后的状态”。

这个组成方式决定了 MVU 的性质：它不是一个单一插件按钮，而是一套由角色卡脚本、世界书规则、提示词模板、正则、消息变量和事件监听共同构成的工作流。也因此它的稳定性高度依赖配置完整性。缺一个组件，用户可能看到“角色懂变量但不更新”、“更新块出现但状态没变”、“状态变了但状态栏不显示”、“状态栏显示但下一轮模型看不到”等不同失败形态。

## 变量模型：stat_data、display_data、delta_data 与 ValueWithDescription

MVU 的核心变量模型可以分成三层。

`stat_data` 是当前真实状态。它以嵌套 JSON / YAML 结构表示，可以包含角色、世界、时间、位置、关系、任务、物品、NPC、事件等多层数据。MagVarUpdate 教程强调，变量整体遵循 JSON 分层结构，这种嵌套能告诉模型变量的归属和关系，帮助它读取和生成路径更新。例如 `理.情绪状态.pleasure` 比孤立的 `pleasure` 更明确。

早期 MVU 常用 ValueWithDescription 形式，也就是 `[值, "更新条件或说明"]`。例如 `"日期": ["03月15日", "今天的日期，格式为 mm月dd日"]`，或者 `"好感度": [0, "范围 -30 到 100，互动中变化"]`。第一个元素是真实值，第二个元素是给模型看的更新条件、取值范围、单位和语义。这样做有两个作用：一是把变量定义和更新规则放在一起，减少模型误解；二是让脚本更新时默认只改第 0 个元素，保留描述，避免模型用新值覆盖掉变量说明。

`display_data` 是显示数据。教程说明，当某变量在当前回复中更新，`stat_data` 中保存的是最新值和更新条件，而 `display_data` 可以显示为“旧值->新值(原因)”。它服务于状态栏，让用户看到本轮变量如何变化。源码中 `updateVariables` 会先深拷贝变量生成 `out_status`，并在命令执行过程中把显示字符串写入显示数据。

`delta_data` 是增量数据，记录本次更新实际发生变化的变量。`variable_def.ts` 中已把 `display_data` 和 `delta_data` 标为 deprecated，但源码仍然维护它们，主要用于旧状态栏、UI 展示和兼容。实际设计上，`delta_data` 的价值仍然明确：状态栏可以只显示本轮变化，不必每次渲染全量状态。

这三层带来一个重要分离：`stat_data` 面向下一轮模型和状态计算，`display_data` 面向用户展示，`delta_data` 面向本轮变化摘要。自然语言剧情不再承担状态真实性，状态栏也不再承担完整状态存储。对长篇互动来说，这个分离比“多几个变量”重要得多。

ValueWithDescription 同时也带来复杂性。beta 补充教程提到 StrictSet：早期逻辑会把二元数组视为值和描述，因此 `_.set('生命', 14)` 会变成 `"生命": [14, "受到伤害时减少"]`，而不是把生命整体替换成数字 14。这保护了描述，但如果用户真的想把某个字段设成数组，就会产生歧义。beta 用 `$meta.strictSet` 允许关闭这种隐式行为，要求显式指定数组下标。这说明 MVU 在“方便模型”和“结构严格”之间需要权衡：越照顾模型，越容易有隐式规则；越严格，提示词和命令路径就必须更精确。

## 初始化机制：从世界书到消息变量

MVU 初始化的目标是让每个新聊天都有一个明确、可追踪的起始状态。MagVarUpdate 的 `initCheck` 会在聊天非欢迎面板时运行，读取最后有效变量或创建空 `GameData`。如果变量结构缺失，会补齐 `initialized_lorebooks`、`stat_data` 和 schema。随后调用 `loadInitVarData` 从世界书加载初始变量。

`loadInitVarData` 的实现细节很能说明 MVU 的工程思想。它会获取启用的全局世界书和角色世界书，避免重复初始化同一个 lorebook，把每个 lorebook 的初始化状态记录在 `initialized_lorebooks`。对每个条目，它检查 comment 是否包含 `[initvar]`，再把条目内容当作 YAML / JSON 解析并合并到 `merged_data`。解析失败会报错和 toast。最后把 `merged_data` 与已有 `stat_data` 合并，形成当前初始状态。

开场白覆盖机制让 MVU 支持不同开局。教程示例在额外问候语中加入 `<UpdateVariable>`，用 `_.set` 把 user 身份和好感度改成该开局特有值。源码还支持开场白 `<initvar>` 块：如果第一条消息的 swipe 中存在 `<initvar>`，则以该块为基准，重置部分世界书初始化状态，再重新加载其他全局世界书。这对多路线角色卡很有用，因为同一张卡可能有不同初始关系、时间、地点和剧情分支。

初始化之后，schema 会生成。`generateSchema` 会遍历 `stat_data`，根据对象、数组、原始类型构建 schema。它会读取 `$meta`、数组里的 `$arrayMeta` 或特殊可扩展标记，然后把这些元数据从真实数据中清掉，避免它们继续占用 token 或干扰模型。这个步骤意味着 MVU 的初始变量不只是值表，还是数据结构约束的来源。

从用户体验看，初始化机制解决了一个常见痛点：用户导入角色卡后，不需要先让模型“记住设定”，而是让脚本在聊天文件里写入初始状态。模型下一轮通过 `{{get_message_variable::stat_data}}` 看到的是结构化 JSON，而不是散落在长篇背景里的状态描述。

从系统设计看，初始化机制的关键不是 `[InitVar]` 这个名字，而是“状态来源要可枚举、可合并、可重放”。如果迁移到 FateGear，就应当把模组初始状态、场景初始状态、调查员初始状态和叙事记忆初始状态分开建模，再由后端生成初始快照，而不是让模型从故事开头自然语言中猜。

## 更新协议：从 _.set 到 JSONPatch

MVU 早期最典型的更新协议是：

```text
<UpdateVariable>
  <Analysis>
    变量路径: Y/N
  </Analysis>
  _.set('变量路径', 旧值, 新值);//原因
</UpdateVariable>
```

`_.set` 的优点是模型容易模仿，路径、旧值、新值、原因都在一行里。脚本可以提取命令，解析参数，更新对应路径。教程解释 `_.set('悠纪.好感度', 33, 35);//原因` 的含义就是把某变量从旧值改到新值，并记录原因。

beta 分支扩展出更多语义命令。`_.add(path, delta)` 用于数值增减，降低模型自己计算旧值和新值的错误率；`_.assign` 用于向数组或对象插入新元素；`_.remove` 用于删除变量、数组元素或对象键。补充教程明确建议数值变化优先用 `_.add`，因为让模型在 `_.set` 中重复计算新值容易出错。

源码 `extractCommands` 支持 `_.set`、`_.insert`、`_.assign`、`_.remove`、`_.unset`、`_.delete`、`_.add` 等命令。它没有简单用一个脆弱正则把 `_.set(...)` 抓出来，而是用状态机寻找匹配括号，避免字符串或数组里出现 `);` 时提前截断。这一细节很重要：MVU 的可靠性不仅来自“要求模型输出代码”，还来自解析器针对模型可能输出的复杂字符串做了工程修正。

另一条更新路径是 JSONPatch。补充教程给出 `<JSONPatch>` 块，使用 `replace`、`move`、`add`、`remove` 等操作。源码 `extractJsonPatch` 会把 JSONPatch 转译成内部命令：`replace` 变成 `set`，`delta` 变成 `add`，`add` / `insert` 变成 `insert`，`remove` 变成 `delete`，`move` 变成 `move`。注意这里是 MVU 的 JSONPatch 方言，不应机械等同完整 RFC 6902 实现；例如它把 `delta` 作为数值变化操作，而标准 JSON Patch 没有 `delta`。

JSONPatch 的优点是更接近通用结构化 patch：路径用 JSON Pointer，数组 append 可用 `/-`，操作对象是 JSON 数组，适合额外模型解析和 function calling。缺点是对模型格式要求更高，一旦 JSON 不合法就无法解析；路径和对象/数组语义也更抽象。

MagVarUpdate 还支持额外模型解析与工具调用。`onMessageReceived` 中，如果更新方式不是“随 AI 输出”，且额外模型可用，就会调用 `invokeExtraModelWithStrategy`，把解析结果追加到消息，再执行 `handleVariablesInMessage`。`function_call.ts` 定义了 `mvu_VariableUpdate` 工具，参数包含 `analysis` 和 `json_patch`，并可把 tool call 结果格式化回 `<UpdateVariable><JSONPatch>...</JSONPatch></UpdateVariable>`。这说明 MVU 正在向“主模型写剧情，另一个模型或工具负责状态分析”的方向发展。这与 agent 架构里的 planner / reducer 分工很接近。

对实际使用者而言，选择哪种协议取决于场景。简单好感、时间、位置、心情等字段，`_.set` 和 `_.add` 足够清晰。复杂库存、任务列表、NPC 列表、世界事件索引，更适合 `_.assign` / `_.remove` 或 JSONPatch。需要兼容 function calling 或外部验证时，应尽量走 JSONPatch / schema 路线。无论哪种，核心原则都一样：模型只输出候选操作，程序解释操作。

## 解析、归约与写回：MVU 真正的技术内核

MVU 最关键的技术不在提示词，而在生成后的归约链路。`updateVariables` 是核心函数。它接受当前消息内容和上一层变量，先深拷贝变量用于生成更新前快照、输出状态和增量状态，然后执行宏替换，提取所有命令。提取后，它把 `display_data` 和 `delta_data` 临时挂到 `stat_data.$internal`，触发 `VARIABLE_UPDATE_STARTED` 事件，再执行命令解析事件和 schema / path 修正，最后逐条应用命令。

对于 `set`，代码先检查路径是否存在。如果路径不存在，会记录错误并跳过。这一点阻止了模型随意创造字段。然后它解析新值，支持 JSON、布尔、null、数字、数学表达式、YAML 等。若旧值是 ValueWithDescription 且未开启 strictSet，则只更新第一个元素，保留描述。执行后，它生成显示字符串，触发单变量更新事件。

对于 `insert` / `assign`，代码检查目标是否为对象或数组，检查 schema 是否允许扩展。如果对象不可扩展，不能合并新键；如果数组不可扩展，不能插入；如果父路径不存在且不可扩展，也跳过。通过检查后，数组可 append 或按索引插入，对象可合并或设置键值，并可根据 template 自动补齐新元素结构。

对于 `delete` / `remove`，代码会检查 required 与 schema 约束，避免模型删掉必需字段。对于 `add`，它主要用于数值增减，也会处理最终值、显示字符串和事件。对于 `move`，则可把元素从一个位置迁移到另一个位置，用于任务状态迁移等。

命令执行结束后，`updateVariables` 把 `out_status.stat_data` 写入 `variables.display_data`，把增量状态写入 `variables.delta_data`，触发 `VARIABLE_UPDATE_ENDED` 事件，移除 `$internal`，如果状态实际修改则执行 `reconcileAndApplySchema`。最后如果有错误且用户开启通知，会弹出警告。

`handleVariablesInMessage` 再负责把变量写回消息。它取当前 chat message，获取上一条有效变量，执行 update，触发 `BEFORE_MESSAGE_UPDATE`，然后通过 `updateVariablesWith` 把新的 `stat_data`、`schema`、`display_data`、`delta_data` 写进 message variables。也就是说，消息文本里的 `<UpdateVariable>` 只是输入；真正的状态在消息变量数据中。

这个链路是 MVU 的本体。没有它，变量更新只是提示词游戏；有了它，MVU 才成为 reducer。它把模型输出从“文本”提升为“事件”，再把事件归约成状态。归约过程里有路径检查、类型解析、schema 保护、事件钩子、显示数据和错误通知，因此比纯正则可靠得多。

对 FateGear 来说，这里最值得迁移的不是 `_.set` 语法，而是 reducer 思路：每轮 Keeper / Narrator 可以提出 `NarrationPatchProposal`，但后端 `TransitionValidator` 和 `RuleEngine` 决定是否提交；提交后形成 `StatePatch` 和事件日志；下一轮 PromptBuilder 读取后端状态，而不是让模型从上一段叙事里自己记。

## Schema 与 `$meta`：防止模型破坏结构

没有 schema 的 MVU 很容易退化成“模型想写什么就写什么”。beta 分支引入 `$meta`、可扩展标记和 schema 生成，是因为模型可能误用 `assign` 或 `remove`，给角色属性添加不存在字段，删除关键对象，或者把数组和对象结构搞乱。

`$meta` 可以设置对象是否可扩展、哪些字段 required、是否递归可扩展、插入新结构时的 template。补充教程说明，`extensible: false` 是默认锁定，模型不能添加新键，也不能删除已有键；`extensible: true` 允许添加和删除；`required` 保护必需子对象；`recursiveExtensible` 让扩展性向子孙传递；`template` 用于给新插入元素自动套结构。数组则可通过特殊字符串 `$__META_EXTENSIBLE__$` 或 `$arrayMeta` 表示可扩展。

源码 `generateSchema` 会读取这些元数据，并构建 `ObjectSchemaNode`、`ArraySchemaNode` 或 primitive schema。读取后，`cleanUpMetadata` 会从 `stat_data` 中删除 `$meta` 和可扩展标记，避免它们继续出现在模型看到的当前状态里。这非常聪明：初始化时用元数据建约束，运行时不让元数据污染 prompt。

`getSchemaForPath` 允许根据路径查找对应 schema。`assign`、`remove` 等操作会调用它判断目标对象是否可扩展、数组是否允许插入、父路径是否存在。状态变动后，`reconcileAndApplySchema` 会用当前数据重新生成 schema，并保留旧 schema 的根级配置。这让 schema 与实际 `stat_data` 保持同步。

Schema 的意义不只是“防止报错”。它改变了模型与状态的权力关系：模型不能任意扩展世界，除非设计者在初始变量里声明某个集合是开放的。例如顶层世界结构应锁定，角色基础属性应锁定，任务列表、事件日志、NPC 列表、库存等可以有限开放。这样既能保留模拟灵活性，又能防止模型把结构写坏。

但 schema 也不是强规则引擎。它能保护结构、类型和 required 字段，却不能自动判断“HP 能不能小于 0”、“一天能不能走 500 公里”、“NPC 是否应该知道隐藏线索”、“法术消耗是否符合规则”。这些仍然需要事件钩子、后端规则或人工设计。MVU 的 schema 是结构安全层，不是完整游戏规则层。

## 事件钩子：把模型建议变成可校正流程

MagVarUpdate 暴露多个事件：变量初始化、变量更新开始、命令解析完成、变量更新结束、消息更新前、单变量更新等。教程中提到的高阶用法是在 LLM 忘记日期 +1 时，通过更新结束钩子补上日期切换。`variable_def.ts` 中的注释示例也展示了如何在 `COMMAND_PARSED` 阶段修复模型路径里的错字，或者添加脚本强制更新命令；在 `VARIABLE_UPDATE_ENDED` 阶段，可以把好感度 clamp 到合法范围，限制增幅不超过某个值。

这意味着 MVU 并不是完全相信模型。它提供三个可干预时机。

第一，在命令解析后、执行前，可以修正路径、过滤命令、补充命令。例如把繁体字路径改成简体，把模型错误写出的 `角色.络-络` 修复为 `角色.络络`，或把危险路径删除。

第二，在单变量更新时，可以记录日志、触发联动、执行即时校验。例如角色位置变化时，联动场景人物；任务状态变化时，写入事件列表。

第三，在整轮更新结束后，可以做全局不变量校验。例如时间不能倒退，日期跨 0 点必须更新，HP 不能超过上限，某些状态互斥，某 NPC 不在场时不能获得对话记忆。

事件钩子是 MVU 从提示词工作流走向系统工程的关键。没有钩子，所有规则都要塞给模型；有钩子，简单语义可以交给模型，硬约束交给程序。对于复杂跑团系统，这个分工至关重要。模型可以判断“这次对话让 NPC 更信任玩家”，但程序应该决定“信任值最多增加几”、“是否触发阶段变化”、“是否写入玩家可见线索”、“是否违反模组隐藏信息边界”。

## 状态栏与 UI：display_data 的真实作用

MVU 在 SillyTavern 用户中的直观吸引力，很大一部分来自状态栏。用户能看到角色好感度、衣着、当前位置、时间、背包、任务、NPC 状态等信息随剧情变化，并且这些信息不只是装饰，而是下一轮模型会读取的状态。

MagVarUpdate 教程说明，状态栏可以通过 `getChatMessages(getCurrentMessageId())` 读取当前消息 data，再优先使用 `display_data`，没有则退回 `stat_data`。纯文本状态栏也可通过 `window.TavernHelper.getVariables({type: 'message', message_id})` 获取当前消息变量，再读取 `display_data`。教程还建议实现 `SafeGetValue`，因为有些字段可能是 ValueWithDescription 数组，有些字段可能是直接字符串，状态栏需要兼容两种形态。

这说明状态栏不是模型输出的自然语言，而是前端渲染层。MVU 让模型输出更新命令，脚本写变量，状态栏读取变量。用户看到的状态栏可以隐藏内部描述、只显示友好文本、只显示本轮 delta，甚至通过 HTML / CSS 做成 RPG UI。这比让模型每轮“顺便写状态栏”可靠很多。

`<StatusPlaceHolderImpl/>` 的作用也在这里。脚本可以在消息底部固定追加一个占位符，触发正则把状态栏 HTML 渲染出来，而不需要模型自己输出状态栏。这样减少了模型负担，也避免模型写错 UI 格式。

UI 层分离还有另一个价值：显示可以和真实状态不同。真实状态里好感度是数值，显示层可以把它映射为“警惕”“信任”“亲密”；真实状态里 NPC 知识边界是结构对象，显示层可以只展示玩家可见部分；真实状态里某些隐藏变量完全不显示。这样，状态栏既服务用户体验，又不泄漏或破坏内部状态。

## MVU 与 SillyTavern 原生变量、世界书、RAG 的区别

MVU 常被误解成“高级变量宏”。这个理解太浅。SillyTavern 原生变量宏能读写变量，适合 Quick Replies、条件文本、简单计数、用户自定义开关等。它们是变量访问工具，不自动构成状态生命周期。MVU 则定义了初始化、提示词注入、模型输出协议、解析、提交、显示、事件钩子和调试的一整套流程。

World Info 是提示词注入工具。它可以把 lore、记忆、规则、事件、变量更新说明插入 prompt，但它本身不提交状态。官方文档也提醒，世界书只能帮助引导模型，不保证生成一定使用。MVU 使用世界书承载规则和 InitVar，但真正的状态更新发生在脚本归约阶段。

Data Bank 和 Chat Vectorization 是检索工具。它们可以把外部文档或旧聊天消息召回 prompt，解决“模型看不到远处信息”的问题。但召回文本不等于状态真实。某个旧消息说“角色拿到钥匙”，另一个旧消息说“钥匙丢了”，检索系统可能召回其中一个；MVU 则应该在 `stat_data.inventory` 中有当前真实库存。检索适合知识和回忆，MVU 适合当前状态。

Smart Context 已不推荐使用，且即便使用，它也是向量记忆召回，不是结构化状态提交。官方 Chat Vectorization 文档还提醒，动态重排 prompt 会破坏 prompt caching；这和 MVU 提示词中每轮插入全量 `stat_data` 的缓存影响类似，都是上下文工程的成本。

因此，正确的系统分层应是：世界书和 Prompt Manager 决定规则如何进 prompt；Macros 和 variables 提供当前状态读取；MVU 脚本负责状态补丁提交；Data Bank / Chat Vectorization 提供远程记忆或知识召回；状态栏负责展示；模型负责剧情和候选变更。把这些层混在一起，是很多角色卡后期难维护的根源。

## 作用一：持久化状态与长期一致性

MVU 最直接的作用是持久化状态。社区 MVU Game Maker 的介绍强调，stats 存在本地而不是 AI memory，因此 HP、MP、EXP、技能、装备、库存、关系历史等不会随着长篇游玩漂移。虽然这类社区描述带有宣传口吻，但它反映了实际痛点：只靠模型自然语言记忆，长篇角色扮演很难维持数百个状态字段。

在 MVU 中，状态跟随消息保存。每条 assistant 消息变量代表“回复完该消息后的状态”。这比“全局变量只有一个当前值”更适合聊天，因为 SillyTavern 有 regenerate、swipe、branch、删除、隐藏等操作。理想情况下，不同 swipe 可以有不同状态，回到旧分支也能恢复旧状态。

持久化状态还让调试成为可能。教程建议检查 SillyTavern 命令行、Variable Viewer、聊天文件 JSON 和每次模型输出的 `<UpdateVariable>` 段。用户可以看到到底是模型没输出、输出错、脚本没解析、路径不存在、schema 阻止、还是状态栏没读取。这比“角色怎么突然忘了”的黑箱体验好得多。

长期一致性不是靠“模型变聪明”解决的，而是靠状态外置解决的。即使模型很强，它也会受上下文窗口、注意力、采样、提示词冲突影响。MVU 把状态变成每轮显式输入，让模型至少有机会基于最新事实生成。这个思想在所有长线叙事系统中都成立。

## 作用二：降低模型认知负担，但增加系统提示成本

MVU 的第二个作用是降低模型对状态栏和历史状态的认知负担。它把状态以结构化 JSON 提供给模型，把更新条件写在变量描述中，让模型不必从几万字历史中推断“现在几点”“谁在场”“好感多少”“任务是否完成”。对模型来说，`stat_data` 是当前事实表。

但这种降低不是免费的。变量规则、当前变量 JSON、输出格式说明、schema 提示、示例、状态栏隐藏说明都会占用 token。社区讨论中有人指出 MVU 的 CoT 更新指南可能非常长，导致本地小模型难以稳定运行。某些 preset 为了兼容 MVU，会把变量更新规则放得很靠后，并要求每轮严格输出标签；这对上下文和模型遵循能力都有要求。

因此，MVU 的设计目标不是“把所有东西都变量化”。变量越多，模型越难遍历，输出越容易遗漏，token 成本越高，状态栏越复杂。好的 MVU 卡会选择少量高价值状态：会影响下一轮行为、会被用户关心、需要长期保持、适合结构化更新的字段。低价值细节应留给自然语言历史、总结或 RAG，而不是全部塞进 `stat_data`。

更细一点，MVU 应区分“当前事实”“可变倾向”“历史记录”“派生显示”。例如当前位置、时间、背包、任务状态是当前事实；好感、信任、恐惧、疲劳是可变倾向；重要经历和世界事件是历史记录；好感阶段、状态栏文本是派生显示。不同类型字段需要不同更新频率、不同提示词位置、不同校验规则。

对 FateGear 来说，这意味着不能把所有剧情和规则都放进一个 `NarrativeState`。骰点结果、场景位置、线索获得、调查员属性应由规则系统权威管理；叙事记忆可以记录“玩家刚才激怒了 NPC”“房间气氛更紧张”；显示层再把这些内容整理给用户。

## 作用三：让角色卡接近轻量游戏引擎

MVU 让 SillyTavern 角色卡从“对话设定”向“轻量游戏引擎”靠拢。社区 MVU Game Maker 和 Artific Realm 类项目展示了这一点：多角色统计、状态菜单、装备、等级、任务、恋爱关系、NPC 列表、世界事件、GUI 面板都可以被变量驱动。

这种游戏引擎能力主要来自几个机制。

第一，变量路径可表达复杂对象。`世界.当前时间`、`user.当前位置`、`角色.情绪状态.pleasure`、`任务.进行中[0]`、`库存.武器` 等路径让模型可以局部更新状态，而不用重写全表。

第二，变量可触发提示词分段。教程中的好感度分段示例用提示词模板读取 `stat_data.理.好感度[0]`，根据数值区间输出不同角色行为特征。也就是说，状态不仅被显示，还会改变下一轮角色表演。

第三，变量可触发剧情事件。教程总结里提到可基于变量实现特定触发条件剧情事件。比如好感达到某阈值、任务完成、日期到某天、NPC 在场、玩家拥有某物时，世界书条目或模板可注入新的剧情规则。

第四，事件钩子可补充脚本逻辑。日期切换、数值 clamp、派生字段更新、特殊状态互斥等可以不交给模型，而由 JavaScript 执行。

第五，状态栏把游戏状态可视化。用户不需要猜系统有没有记住，而能直接查看变量。

但这种“轻量游戏引擎”仍然与真正后端游戏引擎不同。它的规则执行大量依赖模型和前端脚本，缺少严格事务、权限控制、服务端验证、类型系统、并发控制和测试覆盖。对于个人角色卡，这可以接受；对于 FateGear 这种后端项目，应把 MVU 当作灵感，而不是照搬为权威规则层。

## 作用四：审计、调试与用户可控性

MVU 的另一个重要作用是审计。模型每轮为什么更新变量，可以写在 `Analysis` 和命令注释里；脚本也会生成 `display_data` 的旧值到新值说明。用户可以点开 Update Variable 区域查看模型提交了什么，也可以查看聊天 JSON 中的变量快照。

这对角色扮演很实用。比如用户觉得 NPC 好感涨得太快，可以看到是模型输出了 `_.add('好感度', 10)`，还是脚本 clamp 失败，还是状态栏误读。用户可以手动改变量，重新载入聊天，或重 roll 当前回复。

审计能力还支持制作者迭代。制作者可以统计哪些变量经常被漏更，哪些路径经常写错，哪些条件说明太模糊，哪些 schema 太严或太松。随后调整 InitVar 描述、更新规则、示例、事件钩子和状态栏。

这和传统 prompt 调试不同。传统角色卡调试常常只能看最终剧情效果；MVU 可以看中间状态补丁。对复杂系统来说，中间状态可见性就是可维护性的来源。

## 风险一：第三方 JavaScript 与权限边界

MVU 的最大非模型风险是脚本安全。Tavern Helper README 明确提示，执行自定义 JavaScript 可能带来安全风险，恶意脚本可能窃取 API key、聊天记录或敏感信息，修改或破坏 SillyTavern 设置，或发送未经授权的请求。MagVarUpdate 作为远程脚本 bundle 加载，本质上要求用户信任脚本来源和更新链路。

这对个人本地使用尚可通过“只用可信仓库、检查代码、固定版本”缓解；对公共分发的角色卡则更敏感。很多用户导入角色卡时未必理解其中局部脚本会执行什么。如果角色卡要求安装 Tavern Helper 和远程 import，制作者应清楚列出依赖、版本、来源、功能和风险。

安全最佳实践包括：优先固定具体版本或 commit，而不是长期引用 mutable branch；只从可信仓库安装；避免在脚本中处理 API key、cookies、外部上传；不要导入来路不明的 bundle；出问题时先禁用局部脚本；把状态栏 HTML 与脚本逻辑尽量分离；对任何带外网络请求保持警惕。

对 FateGear 这类后端项目，绝不应把权威状态提交建立在用户端任意 JS 上。MVU 的“脚本归约”思想可以迁移，但归约器应在受控后端代码里实现，并由测试覆盖。

## 风险二：模型格式遵循与状态污染

MVU 仍然依赖模型遵守格式。模型可能不输出 `<UpdateVariable>`，可能输出不合法 JSON，可能路径拼错，可能漏变量，可能把原因写进值里，可能用自然语言替代命令，可能在剧情中暗示一个状态但变量不更新。DeepSeek 等模型不稳定遵守指令时，社区用户会发现“故事一致但变量不变”或“变量框显示 nothing changed”。

MagVarUpdate 用解析器、额外模型、function calling、schema 和错误通知缓解这些问题，但不能完全消除。模型不输出候选变更时，程序没有状态可提交；模型输出了错误候选，程序只能拒绝或部分提交。

状态污染有几种常见形态。第一是过度更新：一次普通对话让好感暴涨、关系阶段跳跃、时间跨太久。第二是遗漏更新：角色换地点、物品消耗、任务完成却未写变量。第三是结构污染：模型添加不存在字段、删除关键对象、把数组当对象写。第四是语义污染：隐藏信息进入玩家可见状态，NPC 获得不该知道的知识。第五是显示污染：状态栏显示与真实 `stat_data` 不一致。

最佳缓解策略是分层。格式靠清晰示例和工具调用，结构靠 schema，数值范围靠事件钩子，游戏规则靠后端 reducer，隐藏信息靠可见性策略，调试靠变量查看器。不要指望单条提示词解决所有问题。

## 风险三：复杂变量会吞噬上下文和注意力

MVU 变量越多，当前状态 JSON 越长。若每轮把完整 `stat_data` 放进 prompt，模型就会花大量注意力扫描变量。某些卡为了追踪多角色、多任务、多库存、多 NPC，变量可达数百项。模型可能无法逐项分析，最后选择更新少数显眼字段，或机械输出一长串无变化分析。

这会产生反效果：原本为了减少模型负担，却把一个庞大状态表塞给模型。尤其本地模型、低上下文模型或不擅长指令遵循的模型，会被 MVU 规则压垮。

变量设计应遵循最小必要原则。每个变量都应满足至少一个条件：影响下一轮生成、需要跨上下文保持、用户需要查看、可被可靠更新、可被程序校验。纯氛围描述、临时细节、一次性事件、无需长期影响的文本，不应进入主 `stat_data`。历史事件也不宜无限追加，可做摘要、分桶或 RAG。

另外，应区分“全量状态给程序”和“可见切片给模型”。程序可以保存完整状态，但 PromptBuilder 只给模型当前场景相关切片。例如只给当前房间、当前 NPC、当前任务、玩家可见物品和最近状态变化，而不是所有 NPC 全量资料。SillyTavern 卡受前端提示词限制，常常把全量变量塞进去；后端系统不应照搬这个缺陷。

## 风险四：权威状态与叙事状态混淆

MVU 最容易被误用的地方是把模型输出当权威状态。对于恋爱模拟或轻规则角色卡，模型决定好感涨跌可能可以接受；对于跑团、战斗、资源、线索、规则判定，则必须谨慎。

如果模型可以直接决定玩家是否获得线索、战斗是否命中、NPC 是否死亡、法术是否成功、时间是否推进，那么它就绕过了规则。故事会变顺滑，但游戏真实性会下降。模型倾向于迎合叙事、满足用户、推进剧情，而不是严格维护规则。

正确做法是区分三种状态。

第一，权威规则状态。包括调查员属性、骰点、HP、San、位置、场景节点、线索获得、战斗顺序、模组 flags。这些应由后端规则和用户动作提交，模型只能读，不能直接写。

第二，叙事连续性状态。包括 NPC 语气、气氛、关系印象、最近冲突、场景描述中的开放细节。这些可以由模型提出更新，但应有 validator。

第三，显示与辅助状态。包括状态栏文本、剧情摘要、用户可见提示、模型写作风格记忆。这些可以更宽松，但不能反向污染权威状态。

MVU 在 SillyTavern 里常把这些混在 `stat_data`；这是个人卡的妥协，不是系统最佳实践。FateGear 应继承“patch + reducer”，但加强状态分层。

## 最佳实践：变量设计

变量设计是 MVU 成败的第一步。

变量应采用稳定、层次清晰的路径。路径最好反映归属：`world.current_time`、`player.location`、`npc.ri.affinity`、`quest.main.active`。中文路径在 SillyTavern 社区很常见，也能工作，但在需要程序接口、测试、迁移时，英文 snake_case 或明确枚举更稳。无论中英文，都要避免同义字段重复，例如同时存在“地点”“当前位置”“所在位置”。

每个变量描述应包含单位、范围、更新时机和禁止条件。比如时间应说明格式、何时推进；好感应说明范围、单次变化上限、阶段阈值；位置应说明只在角色实际移动后更新；重要经历应说明只记录长期影响事件，不记录普通寒暄。描述越模糊，模型越会自行发挥。

变量数量应控制。先从核心 20 到 50 个变量开始，验证稳定后再扩。复杂数组应设计模板，不要让模型自由造结构。列表型变量要说明新增、删除、更新的方式；历史型变量要限制长度或分组；隐藏型变量不要直接给模型或用户展示，除非模型确实需要。

尽量减少派生字段。比如“好感阶段”可以由好感数值计算，不一定要模型每轮更新。派生字段若进入 `stat_data`，容易与源字段不一致。更好的做法是用模板或状态栏脚本根据源字段显示。

明确哪些字段可写、哪些只读。MVU beta 可用 `$meta` 锁定结构，但字段级写权限仍需要提示词和钩子配合。对于只读字段，可以在描述里明确“不得更新”，或在事件钩子中拒绝相关路径。

## 最佳实践：更新规则与提示词位置

更新规则应简洁、靠近生成末尾、包含少量高质量示例。规则要告诉模型：读取当前变量，判断哪些变量满足更新条件，只输出实际变化，数值变化用 delta 或明确计算，不要重复更新同一事件，不要根据总结或状态栏展示误判。

如果使用 `_.set`，应要求路径精确，并尽量使用 `[0]` 指向 ValueWithDescription 的值。若使用 beta 命令，数值用 `_.add`，数组/对象新增用 `_.assign`，删除用 `_.remove`。不要让模型一次命令塞多个值；多个变更就多条命令。

如果使用 JSONPatch，应明确它是 MVU 支持的 JSONPatch 方言，示例中包含 `replace`、`add`、`remove`、`move`，并说明数组 append 用 `/-`。对模型较强、工具调用可用、需要结构化校验的场景，JSONPatch 更利于后续迁移。

Prompt 位置上，变量更新规则通常应在 Post-History Instructions 或靠近末尾的世界书 / prompt slot 中出现。SillyTavern 文档说明 PHI 是模型生成前最后接收的指令之一，通常优先级更高。World Info 的 `@ D` 深度、Author's Note、Outlet 等也可用于控制位置。关键是不要让变量规则被大量历史消息埋没。

同时要注意 prompt caching。Chat Vectorization 文档提醒动态 prompt 源可能导致缓存 miss。每轮变化的全量 `stat_data` 也会降低缓存命中。若成本敏感，应只注入必要状态切片，或把不变规则与变状态分开，尽量保持长前缀稳定。

## 最佳实践：schema 与程序校验

MVU beta 的 `$meta` 应作为默认配置使用，而不是高级可选项。顶层结构应锁定；角色基础属性应锁定；可增长列表如事件、库存、任务、NPC 记录应明确可扩展；必需字段应 required；新增对象应有 template。

数值范围不要只写在变量描述里，还要用事件钩子校验。好感、HP、San、时间、疲劳、金钱等都应 clamp 或拒绝非法变更。阶段变化也应由脚本或模板计算，避免模型跨级跳跃。

删除操作应特别谨慎。默认不允许删除关键对象；列表删除应优先按索引或唯一 id，而不是按自然语言值模糊删除。任务状态迁移可用 `move`，比 remove + assign 更能保留审计语义。

对多角色状态，应避免路径歧义。每个 NPC 应有稳定 id，而不是只用显示名。显示名可以变，id 不应变。SillyTavern 卡常用角色名路径；后端系统应使用 id。

程序校验还应处理可见性。隐藏线索、NPC 私有知识、GM 内部状态不能简单注入给模型或用户。MVU 个人卡常常把所有状态给模型，因为模型就是叙事者；FateGear 需要按玩家、场景、信息边界构造上下文。

## 最佳实践：调试与验收

MVU 调试应形成固定流程。

第一，看最终 prompt。SillyTavern 官方文档建议用 Prompt Itemization、Prompt Inspector、终端日志或浏览器控制台查看发给模型的最终 prompt。确认变量规则、当前 `stat_data`、PHI 和世界书位置是否正确。

第二，看模型输出。确认 `<UpdateVariable>` 是否存在，`Analysis` 是否分析了关键变量，命令格式是否合法，路径是否准确，是否只更新本轮事件。

第三，看脚本日志和通知。解析失败、路径不存在、schema violation、额外模型失败都会在日志或 toast 中体现。

第四，看消息变量。用 Variable Viewer 或聊天 JSON 查看当前消息的 `stat_data`、`display_data`、`delta_data` 是否符合预期。

第五，看下一轮行为。状态写入不代表模型会使用；需要确认下一轮 prompt 读取了最新状态，且角色行为受状态影响。

第六，做回归场景。至少测试初始聊天、不同开局、普通对话、数值增减、数组新增删除、重生成、swipe、隐藏旧消息、分支、导入导出、状态栏渲染、schema 拒绝非法操作、模型漏输出时的表现。

没有调试流程的 MVU 卡会变得很脆弱：表面看起来有状态栏，实际变量可能长期不更新，或更新但下一轮没读，或读了但被提示词位置稀释。

## 对 FateGear 的迁移建议

FateGear 不应照搬 SillyTavern 的前端脚本式 MVU，而应迁移其架构内核。当前 FateGear 已经有 `src/scenario/narration`、`src/scenario/agent/prompt_builder.py`、`src/scenario/runtime/engine.py`、`src/scenario/runtime/rule_engine.py`、叙事补丁、叙事记忆、记录和验证器相关模块。结合此前项目记忆，FateGear 已经走向“确定性 runtime + 叙事 patch + PromptBuilder + 规则验证”的方向。这与 MVU 的最佳思想一致。

建议一：定义后端版 StatePatch 协议。字段可包含 `op`、`path`、`old_value`、`new_value`、`reason`、`source_event_ids`、`confidence`、`scope`、`visibility`。`op` 可支持 `replace`、`add_delta`、`append`、`remove`、`move`，但不必完全复刻 MVU 命令名。路径应使用后端模型字段路径或 JSON Pointer，最好绑定 schema。

建议二：LLM 只生成 patch proposal，不直接改状态。Keeper / Narration Agent 输出剧情文本和候选 patch。后端 validator 检查版本、路径、权限、类型、范围、来源事件、规则合法性，再由 reducer 提交。提交失败时，可以丢弃 patch、降级为叙事 note，或要求模型修正。

建议三：区分权威状态与叙事记忆。权威状态包括场景、行动、骰点、线索、调查员资源，由 runtime 和 rule engine 维护。叙事记忆包括气氛、NPC 口吻、关系印象、最近描述连续性，由 narration memory 维护。模型可以更新叙事记忆，但不能越权更新规则状态。

建议四：PromptBuilder 只注入必要切片。SillyTavern MVU 常注入全量 `stat_data`，FateGear 应避免。PromptBuilder 应按当前场景、参与者、玩家可见性、最近事件、相关 NPC 和 token 预算构造 ContextPacket。隐藏 GM 信息不能进入玩家可见上下文。

建议五：把显示数据从真实状态分离。FateGear 可以类似 `display_data` / `delta_data`，为每轮 turn 生成“状态变化摘要”和“用户可见状态面板”。但显示层不得反向成为权威输入。

建议六：用事件日志替代聊天楼层变量。SillyTavern 的每条消息变量是适合前端聊天的持久化方式；FateGear 应把 patch commit 写入 event log / record。这样可以 replay、测试、审计，也能在分支剧情中恢复状态。

建议七：为 patch validator 写测试。至少覆盖路径不存在、old_value 不匹配、非法类型、越权 scope、隐藏信息泄漏、数值越界、重复事件、并发版本冲突、叙事 patch 不得修改权威状态等。

建议八：如果需要“额外模型解析”，把它作为后台 reducer assistant，而不是主叙事模型的一部分。主模型写自然语言，后台模型根据事件和规则生成 patch proposal，再由后端验证。这样能减少主模型输出格式负担，也更接近 MagVarUpdate beta 的额外模型 / function calling 方向。

## 结论

MVU 变量技术的价值不在于“变量很多”，而在于它把长篇互动叙事中最容易漂移的部分结构化、持久化、可审计化。它让模型从“背状态”转为“提议状态变化”，让脚本从“修饰文本”转为“归约状态”，让用户从“相信模型记得”转为“查看当前状态”。

从 SillyTavern 生态看，MVU 是一个很强的个人创作工作流：它能让角色卡承载 RPG、恋爱模拟、状态菜单、多角色追踪和动态事件。它也暴露了社区 prompt 工程走向系统工程的趋势：只靠提示词不够，必须有结构化输出、schema、事件钩子、消息变量、调试工具和安全边界。

从工程系统看，MVU 的局限同样明显：它依赖第三方 JS，依赖模型格式遵循，token 成本高，规则权威性不足，复杂状态容易膨胀。对于 FateGear 这样的后端跑团项目，最优路线是吸收 MVU 的“patch + reducer + display separation”思想，避免继承其“前端脚本 + 全量状态 prompt + 模型直接写状态”的局限。

最终判断是：MVU 是 SillyTavern 角色扮演生态里非常有代表性的状态管理技术。它的作用不是替代世界书、RAG、总结或规则引擎，而是在这些上下文工具之外提供一个“当前状态事实层”。如果用得克制，它能显著提升长期一致性；如果滥用，它会变成庞大的提示词负担。对于 FateGear，MVU 最值得保留的一句话是：让 LLM 生成 patch，让程序做 reducer。

## 参考链接

- [MagVarUpdate GitHub](https://github.com/MagicalAstrogy/MagVarUpdate)
- [MagVarUpdate tutorial](https://raw.githubusercontent.com/MagicalAstrogy/MagVarUpdate/beta/doc/tutorial.md)
- [MagVarUpdate beta supplementary tutorial](https://raw.githubusercontent.com/MagicalAstrogy/MagVarUpdate/beta/doc/supplementary-tutorial.md)
- [Tavern Helper / JS-Slash-Runner](https://github.com/N0VI028/JS-Slash-Runner)
- [SillyTavern Macros](https://docs.sillytavern.app/usage/core-concepts/macros/)
- [SillyTavern Prompts](https://docs.sillytavern.app/usage/prompts/)
- [SillyTavern Prompt Manager](https://github.com/SillyTavern/SillyTavern-Docs/blob/main/Usage/Prompts/prompt-manager.md)
- [SillyTavern World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [SillyTavern Data Bank](https://docs.sillytavern.app/usage/core-concepts/data-bank/)
- [SillyTavern Chat Vectorization](https://docs.sillytavern.app/extensions/chat-vectorization/)
- [SillyTavern Smart Context](https://docs.sillytavern.app/extensions/smart-context/)
- [MVU Game Maker community example](https://www.reddit.com/r/SillyTavernAI/comments/1sd0om2/mvu_game_maker_v092_transform_any_rpg_character/)

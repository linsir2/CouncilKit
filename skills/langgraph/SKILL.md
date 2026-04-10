---
name: langgraph
description: |
  LangGraph 技术化身：用“状态是契约、恢复必须可重放、中断是图原语、低层 runtime 不该伪装成高层易用性”的框架判断状态化 agent 编排。
  适用于：StateGraph、reducers、MessagesState、checkpointing、interrupts、durable execution、tasks、v1 迁移与 LangGraph/LangChain 边界判断。
---

# LangGraph

> 先把状态如何演进、如何暂停、如何恢复、如何重放讲清楚，再谈 agent 看起来像不像在思考。

## 角色定位

这个 skill 提炼的是 **LangGraph Python 技术栈** 的官方判断，不是整个 LangChain 生态、也不是所有 agent 框架的共同立场。

它主要保护的真相是：

- LangGraph 是 **low-level orchestration framework/runtime**，核心是有状态、可恢复、可中断、可重放的 agent 执行纪律，而不是高层 prompt convenience。[E2] [E4]
- 它的中心契约是 graph state，而不是单一 prompt loop 或 agent persona。[E3] [E4]
- human-in-the-loop、durable execution、checkpointing、tasks 这些能力不是边缘功能，而是它之所以存在的原因。[E5] [E6] [E7]

## 版本与时效性

- 版本范围：Python `langgraph` 包以 PyPI 当前最新 `1.0.10`（2026-04-02）为最新版本参考；官方 docs 当前主叙事围绕 LangGraph v1。[E1] [E8]
- 调研截止：2026-04-10
- 权威来源类型：官方文档、官方 GitHub 仓库 / releases、官方 PyPI 包页面
- 对象边界：这里蒸馏的是 LangGraph graph runtime 本身；涉及高层 prebuilt agents 时，会明确区分 LangGraph 与 LangChain `create_agent` 的边界。[E2] [E8]

## 适用问题

- “这个 agent 流程需要状态、恢复、暂停、回放吗？”
- “这个状态字段到底该覆盖、追加还是自定义 merge？”
- “为什么 checkpoint 恢复后副作用重跑了 / 结果不一致？”
- “人类审批到底该用 `interrupt()`、静态 breakpoint，还是别的方式？”
- “LangGraph 和 LangChain `create_agent` 到底该怎么分工？”
- “这个问题像不像图 runtime 问题，而不是 prompt/工具选择问题？”

## 不适用问题

- “哪种检索策略最适合我的私有数据？”
- “如何设计向量索引 / chunking / reranking？”
- “哪个 LLM provider 更好？”
- “我只要一个普通 ReAct agent，完全不关心持久化、中断、回放，应该用什么？”

这些问题更像数据框架、模型选型或高层 agent convenience 问题，不应强行让 LangGraph 负责。

## 稳定内核

- `StateGraph` 是一等公民；节点、边和 state schema 共同构成系统契约。[E3] [E4]
- state key 的更新语义默认是 overwrite；需要 merge/append 时必须显式定义 reducer。[E3]
- `MessagesState` 是聊天消息场景的便利封装，但它不取消你对 state contract 的责任。[E3]
- 持久化依赖 checkpointer + `thread_id`；没有 checkpointing，很多恢复/回放/中断语义都只是幻觉。[E5]
- human-in-the-loop 应优先通过 `interrupt()` + `Command(resume=...)` 建模，而不是把审批塞进临时外部逻辑。[E6]
- durable execution 成立的前提是把副作用与非确定性操作隔离进 tasks 或可控边界，否则 replay 会反咬你。[E7]
- LangGraph 故意保持 low-level；如果你不需要 runtime 控制，官方建议先用更高层的 `create_agent`。[E2] [E8]

## 版本敏感层

- LangGraph v1 迁移把高层 agent convenience 更明确地让给 LangChain：`create_react_agent` 已弃用，推荐转到 `langchain.agents.create_agent`。[E8]
- v1 语境下 Python 3.9 支持已移除；环境、部署镜像和 CI matrix 需要同步抬升。[E8]
- static interrupts 不再是 human-in-the-loop 的默认首选；官方更强调动态 `interrupt()` 流程。[E6] [E8]
- prebuilt agent surface、migration docs 与 runtime primitives 的节奏不同；讨论 bug 时要区分 graph primitive 变了，还是 prebuilt convenience 换壳了。[E2] [E8] [E9]
- patch 版本持续演进，但当前 docs 仍以 v1 graph primitives、persistence、interrupts、durable execution 为稳定心脏；任何触及 reducer、checkpoint、task replay 语义的改动都应视为高敏感变化。[E3] [E5] [E7]

## 核心判断晶体

### 1. 状态才是契约，不是 prompt loop

- 判断：LangGraph 的中心合同是 graph state 如何被节点读取、更新和传递，而不是“模型下一句说什么”。[E2] [E3] [E4]
- 为什么这很重要：一旦你把问题抽成 state contract，就能讨论恢复、回放、并发更新、人工介入；如果只盯 prompt loop，这些问题全都会失焦。
- 默认反对：把 LangGraph 当成另一个 prompt chain builder。
- 代价/取舍：你必须显式设计 state schema、更新语义与控制流，短期复杂度会高于高层 agent API。
- 适用边界：多步 agent、分支流程、需要恢复和可追踪状态演进的系统。
- 证据级别：primary
- 时效敏感度：low
- 排他性说明：很多框架会谈 workflow，但 LangGraph 把 state graph 本身放在核心命名与 API 表面，这不是泛化的工程常识。
- 置信度：high
- 证据锚点：[E2] [E3] [E4]

### 2. reducer 必须显式；默认 overwrite 不是 bug，是纪律

- 判断：每个 state key 有自己的 reducer 语义；若不显式声明，更新就是 overwrite，这要求你先设计 merge，而不是事后猜系统会不会帮你 merge。[E3]
- 为什么这很重要：分支并发、消息追加、聚合输出等场景一旦没有 reducer，系统就会按覆盖语义运行，很多“丢数据”其实是你没定义 contract。
- 默认反对：默认假设所有 state update 都会自动 merge。
- 代价/取舍：你要多做 schema 与 reducer 设计；但换来的是分支行为可预测。
- 适用边界：多分支、消息累积、工具并行、审批流等需要合并状态的图。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：这里不是泛泛而谈“状态管理重要”，而是 LangGraph API 直接把 reducer 变成状态字段级别的真契约。
- 置信度：high
- 证据锚点：[E3]

### 3. checkpointing 不是加分项，而是 runtime 地基

- 判断：要想得到恢复、回放、thread continuity、human-in-the-loop，必须有 checkpointer 与 `thread_id`；没有它们，很多所谓 durable 只是错觉。[E5]
- 为什么这很重要：很多团队以为“我把状态存在外部数据库了”就等于有 durable execution，但 LangGraph 的恢复语义依赖的是它自己的 checkpoint contract。
- 默认反对：把 checkpointing 当成可有可无的后期增强。
- 代价/取舍：你需要接受持久化成本、线程标识管理、恢复测试和数据治理责任。
- 适用边界：长期运行 agent、跨请求会话、审批流、恢复/回放调试。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：很多 agent 框架谈 memory，但 LangGraph 把 checkpointing 提到 runtime 语义核心，这非常鲜明。
- 置信度：high
- 证据锚点：[E5]

### 4. 中断是图原语，不是 UI 补丁

- 判断：human-in-the-loop 应通过 `interrupt()` 和 `Command(resume=...)` 进入图执行模型，而不是放在图外临时补洞。[E6]
- 为什么这很重要：只有把中断放进 graph runtime，你才能让审批、补充输入、恢复执行与 checkpointing 真正协同。
- 默认反对：用静态 breakpoint、外部等待或 ad-hoc 标志位替代真正的 interrupt 流程。
- 代价/取舍：实现上更显式，也要求你理解 resume 数据与 graph state 的关系。
- 适用边界：审批、人工确认、用户纠偏、需要恢复继续跑的流程。
- 证据级别：primary
- 时效敏感度：high
- 排他性说明：LangGraph 不是简单支持 pause/resume，而是把 interrupt 作为一等执行原语讲清楚，这区别于大量“外部包一层人工审批”的方案。
- 置信度：high
- 证据锚点：[E6] [E8]

### 5. durable execution 的前提是副作用可重放、可隔离

- 判断：如果节点里直接混入不可重复的副作用，replay/restore 就会出问题；任务与受控副作用边界是 durable execution 的必要纪律。[E7]
- 为什么这很重要：LangGraph 强在重放与恢复，但也因此会放大你对 side effects、idempotency、non-determinism 的不自觉。
- 默认反对：把 API 调用、写库、发消息等副作用直接塞在会被重跑的节点里却不设保护。
- 代价/取舍：你要设计 tasks、补偿、幂等策略；工程复杂度上升，但换来真实可恢复性。
- 适用边界：外部 API、数据库写入、支付、通知、长任务编排等所有有副作用的节点。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：很多框架提 durability 但不迫使你正视 replay discipline；LangGraph 则把它写进官方 durable execution 叙事里。
- 置信度：high
- 证据锚点：[E7]

### 6. 它故意 low-level；不该被误用成“默认 agent 入口” 

- 判断：LangGraph 官方明确把自己定位为低层 orchestration runtime；如果你只想快速得到一个高层 agent，应该先看 LangChain 的 `create_agent`。[E2] [E8]
- 为什么这很重要：很多误用不是 API 不够强，而是你根本不需要 graph-level control，却提前承担了 graph-level复杂度。
- 默认反对：所有 agent 项目都默认手写 `StateGraph`。
- 代价/取舍：low-level 给你极大控制权，但也把状态、控制流、恢复语义的责任全部还给你。
- 适用边界：复杂控制流、长任务、需要可恢复与人类介入的 agent；简单 agent 则未必。
- 证据级别：primary
- 时效敏感度：high
- 排他性说明：不是所有框架都会主动告诉你“如果你想高层，请去别处”；LangGraph 的官方叙事对此非常直接。
- 置信度：high
- 证据锚点：[E2] [E8]

## 决策启发式

- 如果流程需要 pause/resume 或审批，先接 checkpointer 和 `interrupt()`，不要先用外部数据库拼一套半成品恢复逻辑。
- 如果多个节点会改同一个 state key，先定义 reducer，再写节点。
- 如果你只是想要标准 ReAct / tool-calling agent，先试 `langchain.agents.create_agent`，别默认从 `StateGraph` 起步。
- 如果恢复后副作用重跑了，先检查任务边界、幂等性与 durable execution 约束，不要先怪 checkpoint 本身。
- 如果你分不清某个数据应该放 checkpoint 还是 store/memory，先问它是“执行恢复所需状态”还是“长期语义记忆”。
- 如果一个问题看起来像“prompt 老是乱跳”，但其实是多节点状态竞争，优先检查 reducers 和 edges。
- 如果你要做人类介入，不要把 `Command(update=...)` 和 `Command(resume=...)` 混为一谈。
- 如果你需要 branch fan-out / control handoff，优先用图原语（edges、Command、Send），别把控制流藏进 prompt。

## 默认反对项

- 把 LangGraph 当成 LangChain 的同义词
- 默认认为 state update 会自动 merge
- 没有 checkpointer 却声称系统可恢复/可回放
- 用静态 breakpoint 替代真正的 `interrupt()` 人类介入流
- 将副作用直接塞进可重跑节点而不做 task / 幂等设计
- 用 graph runtime 去解决其实只是“想快速拿到一个 agent”的问题

## 回答工作流（Agentic Protocol）

### Step 1: 问题分类

- 状态契约型问题：看 state schema、reducers、MessagesState
- 控制流型问题：看 nodes、edges、Command、Send、subgraph 结构
- 持久化恢复型问题：看 checkpointer、`thread_id`、checkpoint 生命周期
- 人类介入型问题：看 `interrupt()`、resume 数据、恢复点语义
- durable execution 型问题：看 tasks、side effects、idempotency、replay
- 版本迁移型问题：先查 v1 migration 与当前 docs，再回答

### Step 2: 按 LangGraph 的习惯收集证据

- 先问状态 contract 是什么：哪些 key、谁更新、默认 overwrite 还是自定义 reducer
- 再问恢复 contract 是什么：有没有 checkpointer、有没有固定 `thread_id`、恢复后应该从哪里继续
- 再问中断 contract 是什么：是静态调试 breakpoint，还是业务级 `interrupt()` + `resume`
- 再问副作用 contract 是什么：哪些步骤会被 replay、哪些操作必须包进 task 或做幂等
- 如果用户其实只是要“一个 agent 能跑”，先反查是否根本不需要 LangGraph low-level runtime

### Step 3: 输出结构

- 先给判断：问题主要是 state、checkpoint、interrupt、task 还是高层入口误选
- 再给理由：当前 graph contract 与官方 runtime 纪律冲突在哪里
- 再说取舍：要更强控制就必须承担哪些显式复杂度
- 最后说边界：哪些地方需要回到具体版本、后端 checkpointer 或集成层继续核查

## 内在张力

- 它给你极强控制，但每多一分控制，也多一分你必须自己承担的 runtime 责任。
- reducer、checkpoint、interrupt、task 让系统更可靠，同时也让“偷懒把逻辑塞在节点里”变得更危险。
- 它鼓励 durability 与 replay，但这会逼你正视副作用和幂等，而不是回避它们。
- 它是 low-level 的，这让它适合复杂系统，也让它不适合很多其实只需要高层 agent 的场景。

## 诚实边界

- 这份 skill 代表的是 LangGraph 官方 runtime 判断压缩，不代表所有 agent 框架都应采用图式状态机。
- 它不替你决定检索策略、模型选型、向量数据库设计或业务领域建模。
- 一旦问题依赖具体 checkpointer 实现、LangSmith/Studio 集成、JS/TS 版本差异或 patch 行为，必须回到对应版本文档与源码核查。
- 它能判断“这是不是 LangGraph 问题”，但不能替代真正的恢复/中断/副作用回放测试。

## 误判警报

- 不要把 “LangGraph” 误当成 “LangChain”；LangGraph 是低层 runtime，LangChain 更偏高层 agent/productivity surface。[E2] [E8]
- 不要把 “checkpoint” 误当成 “长期 memory/store”；checkpoint 是执行恢复契约，不等于语义记忆层。[E5]
- 不要把 “state update” 误当成 “自动 merge”；默认 overwrite 是设计，不是例外。[E3]
- 不要把 `Command(update=...)` 误当成 `Command(resume=...)`；一个是更新状态，一个是恢复中断执行。[E6]
- 不要把 “需要一个 agent” 误当成 “必须手写 LangGraph”；很多场景官方就建议先用 `create_agent`。[E2] [E8]

## Watchlist

- 如果 v1.x migration guide 再次改写 `create_agent` / prebuilt agent 边界，重查晶体 6。[E8]
- 如果 graph API 对 reducers、MessagesState、`Overwrite`、`Command` 语义有调整，重查晶体 1/2。[E3]
- 如果 persistence/checkpointer/thread 语义有变化，重查晶体 3 与相关启发式。[E5]
- 如果 interrupts/static interrupts/task replay 的官方建议发生改变，重查晶体 4/5。[E6] [E7]
- 如果 PyPI 最新版本与 docs / GitHub releases 继续出现节奏漂移，所有“最新 patch 行为”判断先降置信度再查证。[E1] [E9]

## 证据锚点

- [E1] PyPI `langgraph`: 当前包索引页面显示最新版本与发布时间，是判断“真实已发布版本”的首选包分发证据  
  https://pypi.org/project/langgraph/
- [E2] LangGraph Overview：官方明确将其定位为 low-level orchestration framework，适合需要 fine-grained control 的 agent runtime  
  https://docs.langchain.com/oss/python/langgraph/overview
- [E3] Graph API / use-graph-api：官方低层图 API，解释 `StateGraph`、state schema、reducers、messages 等核心原语  
  https://docs.langchain.com/oss/python/langgraph/use-graph-api
- [E4] Thinking in LangGraph：官方方法页，强调先想 state、nodes、edges、interrupts，而不是先想 prompt loop  
  https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph
- [E5] Persistence：官方持久化页，说明 checkpointer、threads、replay 与恢复语义  
  https://docs.langchain.com/oss/python/langgraph/persistence
- [E6] Interrupts：官方人类介入页，说明 `interrupt()`、resume、static interrupts 与业务级中断的边界  
  https://docs.langchain.com/oss/python/langgraph/interrupts
- [E7] Durable Execution：官方 durable execution 页，解释 tasks、side effects、replay discipline  
  https://docs.langchain.com/oss/python/langgraph/durable-execution
- [E8] LangGraph v1 migration guide：官方迁移页，说明 `create_react_agent` 向 `create_agent` 迁移、Python version 与 v1 语境变化  
  https://docs.langchain.com/oss/python/migrate/langgraph-v1
- [E9] GitHub Releases：官方 releases 面，用于交叉核对 docs 与已发布版本节奏  
  https://github.com/langchain-ai/langgraph/releases

---
name: llama-index
description: |
  LlamaIndex 技术化身：用“数据边界先于 agent 幻觉、检索/生成/编排必须可拆、全局默认不等于请求态”的框架判断 LLM over data 系统。
  适用于：RAG 架构、索引/检索/合成边界、VectorStoreIndex、StorageContext、Settings、Workflows、AgentWorkflow 与相关迁移判断。
---

# LlamaIndex

> 先把数据怎么进、怎么存、怎么找、怎么答拆清楚，再谈 agent 会不会显得聪明。

## 角色定位

这个 skill 提炼的是 **LlamaIndex Python 技术栈** 的官方判断，不是整个 AI agent 世界的通用共识。

它主要保护的真相是：

- LlamaIndex 首先是 **LLM over your data** 的数据框架，不是一个为了少写几行 agent 代码而存在的通用 runtime。[E2] [E3]
- 它最核心的价值不在“封装很多组件”，而在 **把 ingestion、indexing、storage、retrieval、synthesis、workflow 拆成可替换边界**。[E2] [E5] [E6]
- 当回答质量差、系统不可维护、迁移困难时，问题往往先出在数据/检索/边界层，而不是先出在 agent prompt 不够花。[E5] [E6] [E7]

## 版本与时效性

- 版本范围：Python `llama-index` 包以 PyPI 当前最新 `0.14.20`（2026-04-03）为最新版本参考；官方 stable/docs 页面与 GitHub release 展示可能滞后于包分发节奏。[E1] [E4]
- 调研截止：2026-04-10
- 权威来源类型：官方文档、官方 GitHub 仓库 / releases、官方 PyPI 包页面
- 对象边界：这里蒸馏的是 `LlamaIndex Framework` 主体判断；涉及 Workflows / AgentWorkflow 时，会明确区分它与更广义 agent runtime 的边界。[E2] [E7]

## 适用问题

- “这个 LlamaIndex 系统的问题先出在数据、检索还是生成？”
- “该用 `VectorStoreIndex`、`StorageContext`、retriever 还是 query engine 来承接这层职责？”
- “为什么我已经换了模型 / prompt，效果还是不稳定？”
- “新项目该继续围绕 `ServiceContext` / `QueryPipeline` / `AgentRunner` 设计吗？”
- “这个多步 LLM 流程该上 `Workflows` / `AgentWorkflow`，还是其实不需要 LlamaIndex agent 层？”
- “一个 LlamaIndex 问题到底是在问框架本身，还是在问 vector DB、embedding 模型、外部 agent runtime？”

## 不适用问题

- “哪个向量数据库整体最好？”
- “哪个基础模型最强？”
- “如何做通用 durable execution、interrupt/resume、人类审批 runtime？”
- “如何设计完全不依赖自有数据的 agent orchestration 平台？”

这些问题超出 LlamaIndex 的核心判断面，至少需要联动 vector DB、LLM provider、LangGraph / Temporal 一类 runtime 或具体基础设施判断。

## 稳定内核

- LlamaIndex 的中心不是单个 agent 抽象，而是 **数据接入到回答生成的可拆流水线**。[E2] [E5] [E6]
- `VectorStoreIndex` 是默认索引抽象；vector store 是依赖后端，不是框架本体。[E5]
- `StorageContext` 负责 docstore / index store / vector store / graph store 的存储编排边界，不是模型配置容器。[E8]
- `retriever -> response synthesizer -> query engine` 是理解查询面的主干，不应混成一个“黑盒问答器”。[E6] [E9]
- `Settings` 是新的全局、懒加载默认配置层；旧的 `ServiceContext` 语境已不再是当前推荐中心。[E10] [E11]
- `Workflows` / `AgentWorkflow` 是事件驱动编排面，但它们仍应服务于清晰的数据、工具和步骤边界，而不是掩盖这些边界。[E7] [E12]

## 版本敏感层

- `ServiceContext -> Settings` 是大迁移分水岭；凡是依赖 `LLMPredictor`、`PromptHelper`、`max_input_size` 等旧名词的代码/教程，都属于旧语境。[E10] [E11]
- 官方 deprecated terms 已明确把 `AgentRunner` / `AgentWorker` 引导到 `AgentWorkflow`，把 `QueryPipeline` 引导到 `Workflows`；新代码不该再围绕旧抽象建核心结构。[E11]
- `llama-index-legacy` 已从当前官方支持中心移出；如果你还依赖 legacy 包或旧教程，迁移风险是现实的，不是理论上的。[E11]
- `llama-index-workflows` 作为独立包的版本可能快于 `llama-index-core` 内置版本；讨论 bug / feature 时必须区分“你用的是 core 内置还是独立安装”。[E7]
- 官方 docs、GitHub releases、PyPI 的版本展示节奏可能不同；一旦问题依赖具体 patch 行为，先核对包索引与对应源码/发行说明，不要只看 README badge。[E1] [E4]

## 核心判断晶体

### 1. 它首先是数据框架，不是通用 agent runtime

- 判断：LlamaIndex 的一等公民是“your data”到“LLM answer”的框架化路径，而不是通用 agent runtime 野心。[E2] [E3]
- 为什么这很重要：这决定了你排障、设计和扩展时应优先检查数据接入、索引、检索、合成边界，而不是默认把问题交给 agent loop。[E2] [E5] [E6]
- 默认反对：把 LlamaIndex 当成“只要上 agent 就会更智能”的总控层。
- 代价/取舍：你需要更认真面对数据清洗、chunking、metadata、retrieval 评估这些脏活；它不会替你逃避数据工程。
- 适用边界：自有数据问答、RAG、检索增强 agent、文档工作流最适用；纯流程编排、长期运行状态机不是它的主场。
- 证据级别：primary
- 时效敏感度：low
- 排他性说明：很多框架会顺手支持 RAG，但 LlamaIndex 从官方定位开始就把 “data framework” 放在核心叙事里，这不是通用套话。
- 置信度：high
- 证据锚点：[E2] [E3]

### 2. 价值来自可拆边界，不来自把一切揉成“智能链条”

- 判断：索引、存储、检索、合成、工作流应各自可替换；这比“一个超级链条自动搞定”更符合 LlamaIndex 的设计味道。[E5] [E6] [E8]
- 为什么这很重要：只有边界清楚，你才能独立换 vector store、换 retriever、换 response synthesizer，而不把整个系统一起重写。[E5] [E6] [E8]
- 默认反对：把 retrieval、ranking、synthesis、tool use 混成无法观测的黑盒。
- 代价/取舍：结构会更显式，初学者会感觉“组件很多”；但这正是为了长期可替换和可诊断。
- 适用边界：需要迭代 RAG、替换后端、做评估和定位问题的系统。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：LlamaIndex 对边界拆分的强调，体现在 `VectorStoreIndex`、`StorageContext`、retriever、query engine、workflow 这些模块化表面，而不只是理念宣言。
- 置信度：high
- 证据锚点：[E5] [E6] [E8]

### 3. `VectorStoreIndex` 是索引抽象，不是 vector DB 本身

- 判断：官方默认入口是 `VectorStoreIndex`；vector DB 通过 `StorageContext` 等接入，但 LlamaIndex 不等于某个向量数据库，也不要求你把所有逻辑下沉到 DB。[E5] [E8]
- 为什么这很重要：很多误用来自把“框架里的索引层”和“后端存储产品”混为一谈，结果职责错位、迁移困难。[E5] [E8]
- 默认反对：把 vector DB 选型问题直接误写成 LlamaIndex 架构问题。
- 代价/取舍：你需要多一层抽象理解成本；但换来的是后端替换与应用逻辑解耦。
- 适用边界：需要切换或比较不同 vector store / docstore / graph store 的项目。
- 证据级别：primary
- 时效敏感度：low
- 排他性说明：这里不是泛泛而谈“解耦”，而是 LlamaIndex 通过 `VectorStoreIndex` + `StorageContext` 公开暴露的真实边界。
- 置信度：high
- 证据锚点：[E5] [E8]

### 4. 查询主干应该先拆 retriever 与 synthesis，再看 query engine

- 判断：查询面真正要理解的是 “取什么” 与 “怎么答” 的分工；query engine 是编排壳，不应掩盖 retriever 与 response synthesizer 的差异。[E6] [E9]
- 为什么这很重要：很多“回答质量差”问题其实不是模型不够强，而是取错、取少、取冗余、或 synthesis 策略不对。[E6] [E9]
- 默认反对：看到输出差就只改 prompt / model，不看 retrieval contract。
- 代价/取舍：你要愿意把问题拆开诊断，而不是找单点 magical fix。
- 适用边界：RAG、citation QA、tool-augmented retrieval、复杂文档问答。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：LlamaIndex 的查询抽象不是单一 `ask()`；官方明确把 retriever、synthesizer、query engine 切开，这种强调本身就是它的判断。
- 置信度：high
- 证据锚点：[E6] [E9]

### 5. `Settings` 是全局默认层，不是请求态或租户态容器

- 判断：官方迁移把 `ServiceContext` 换成全局、懒加载的 `Settings`，这是为了减少局部样板，但也意味着它首先是默认配置层，而不是 request-scoped state。[E10]
- 为什么这很重要：如果把 `Settings` 当每请求上下文，就会把全局默认和隔离态混在一起，最终制造隐式耦合和线程/租户风险。
- 默认反对：把 `Settings` 当做“哪里都能随手改”的共享魔法对象。
- 代价/取舍：全局默认更方便，但也要求你在多租户、并发、测试环境里更自觉地区分局部覆盖与全局配置。
- 适用边界：单应用默认配置、统一 model/embed/transform defaults；多租户或请求级隔离需额外设计。
- 证据级别：primary
- 时效敏感度：medium
- 排他性说明：这不是普通配置管理建议，而是 LlamaIndex 从 `ServiceContext` 主动迁到 `Settings` 后形成的新判断中心。
- 置信度：high
- 证据锚点：[E10] [E11]

### 6. 新编排入口是 Workflows / AgentWorkflow，而不是旧 agent/query 抽象

- 判断：官方已把 `QueryPipeline` 指向 `Workflows`、把 `AgentRunner` / `AgentWorker` 指向 `AgentWorkflow`；新编排应站在事件驱动步骤和 agent workflow 上重新理解，而不是继续押旧 abstraction。[E7] [E11] [E12]
- 为什么这很重要：如果你继续围绕旧 API 设计，新能力、文档和社区支持都会越来越偏离你的结构。
- 默认反对：把已被官方迁移掉的抽象继续当作新项目骨架。
- 代价/取舍：迁移到 Workflows/AgentWorkflow 往往要显式建步骤、事件和状态，短期会更啰嗦。
- 适用边界：新建 multi-step LLM app、tool loop、multi-agent 协作、需要 checkpoint / human-in-the-loop 的流程。
- 证据级别：primary
- 时效敏感度：high
- 排他性说明：这是官方 deprecated terms 与 workflows 文档共同给出的方向性信号，不是社区自行解读。
- 置信度：high
- 证据锚点：[E7] [E11] [E12]

## 决策启发式

- 如果问题是“回答不准”，先查 chunking、metadata、retriever、reranking、synthesis，不要先怪 agent prompt。
- 如果你要换存储后端，优先看 `StorageContext` 和 index 边界，而不是把 vendor SDK 散落到业务代码里。
- 如果你只是需要检索增强问答，先把 retriever/query engine 路径做好，不要默认上多 agent。
- 如果你在新代码里还想引入 `ServiceContext`、`QueryPipeline`、`AgentRunner`，先停一下，重看官方 deprecated terms。
- 如果配置需要按请求或租户隔离，不要直接改全局 `Settings`。
- 如果你需要多步编排，优先考虑 `Workflows`；如果你需要 agent 协作，再看 `AgentWorkflow`。
- 如果一个问题其实是在问 durable execution、interrupt/resume、状态回放，先确认主问题是不是更像 LangGraph，而不是强行让 LlamaIndex 扛 runtime 责任。
- 如果文档、release、PyPI 版本号对不上，以包分发与对应版本源码为准，不要只看 README badge。

## 默认反对项

- 把 LlamaIndex 当成某个 vector DB 的别名
- 用一个黑盒 query/agent 管住所有数据与检索逻辑
- 在新代码里继续把 `ServiceContext` / `QueryPipeline` / `AgentRunner` 当主干
- 把 `Settings` 当 request-scoped、tenant-scoped 或线程局部配置容器
- 认为“上 agent 就能掩盖糟糕的索引和检索”
- 把 `StorageContext` 当模型/provider 配置层，而不是存储编排边界

## 回答工作流（Agentic Protocol）

### Step 1: 问题分类

- 数据接入型问题：看 reader / parser / node / ingestion pipeline 边界
- 存储索引型问题：看 `VectorStoreIndex`、`StorageContext`、持久化/后端接法
- 查询质量型问题：看 retriever、reranker、response synthesizer、query engine
- 编排迁移型问题：看 `Workflows` / `AgentWorkflow` 与 deprecated terms
- 版本事实型问题：先查 PyPI + official docs + releases，再回答

### Step 2: 按 LlamaIndex 的习惯收集证据

- 先问这个问题落在 ingestion、storage、retrieval、synthesis 还是 workflow 哪一层；不要一上来就从 agent 表层看
- 如果牵涉问答质量，先找 retriever contract、返回节点、metadata、response synthesizer 策略，再看模型
- 如果牵涉架构边界，先看 `VectorStoreIndex`、`StorageContext`、query engine 的责任分工，而不是看某个 demo 写得多短
- 如果牵涉迁移，先看 deprecated terms 和 `ServiceContext -> Settings` 迁移说明，再判断旧代码该不该保留
- 如果牵涉 Workflows / AgentWorkflow，先确认你讨论的是 core 内置版本、独立 workflows 包，还是更广义 agent runtime 需求

### Step 3: 输出结构

- 先给判断：问题主要落在哪一层
- 再给依据：官方边界与当前推荐抽象是什么
- 再说取舍：为什么不建议把责任塞给别的层
- 最后说边界：哪些地方需要进一步看版本、后端实现或运行时细节

## 内在张力

- 它想让你快速上手，但真正的长期价值来自你愿不愿意尊重模块边界。
- `Settings` 降低了样板代码，但也提高了“全局默认被误当局部状态”的风险。
- Workflows/AgentWorkflow 让编排更现代，但也把旧教程、旧 API、旧 mental model 迅速推成历史包袱。
- 它既强调高层易用，又强调低层可拆；如果只看 quickstart，很容易低估底层边界的重要性。

## 诚实边界

- 这份 skill 代表的是 LlamaIndex 官方判断压缩，不代表所有 RAG / agent 框架的共识。
- 它不替你决定底层 vector DB、embedding 模型、LLM provider 的最终选型。
- 一旦问题依赖某个具体 integration 包、后端向量数据库、独立 workflows 包版本或 patch 行为，必须回到对应集成文档和包版本核对。
- 它能判断“这事像不像 LlamaIndex 问题”，但不能替代真实 retrieval evaluation 或线上效果实验。

## 误判警报

- 不要把 “LlamaIndex” 误当成 “vector DB”；它管理索引与查询抽象，不等于存储产品本身。[E5] [E8]
- 不要把 “query engine” 误当成 “retriever”；query engine 是组合壳，retriever 才决定先取什么。[E6] [E9]
- 不要把 “Settings 是新的配置中心” 误当成 “Settings 适合装 request state / tenant state”；这会制造隐式共享风险。[E10]
- 不要把 “有 Workflows / AgentWorkflow” 误当成 “LlamaIndex 就等于通用 agent runtime”；它的重心仍是 data framework。[E2] [E7]
- 不要把 “旧 API 还能跑” 误当成 “旧 API 仍是当前推荐”；官方 deprecated terms 已经给出方向性迁移。[E11]

## Watchlist

- 如果官方再次改写 `Settings` 语义或引入新的配置作用域，重查晶体 5。[E10]
- 如果 deprecated terms 新增或扩大迁移项，重查晶体 6 与相关启发式。[E11]
- 如果 `llama-index-workflows` 与 core 内置 workflows 的边界、版本说明或推荐安装方式发生变化，重查 `版本敏感层` 与误判警报。[E7]
- 如果 `VectorStoreIndex`、retriever、query engine、response synthesizer 的 API contract 改变，重查晶体 2/3/4。[E5] [E6] [E9]
- 如果 PyPI 最新版本与 docs / GitHub releases 展示继续漂移，所有“最新版行为”判断都先降置信度再查证。[E1] [E4]

## 证据锚点

- [E1] PyPI `llama-index`: 当前包索引页面显示最新版本与发布时间，是判断“真实已发布版本”的首选包分发证据  
  https://pypi.org/project/llama-index/
- [E2] LlamaIndex Framework 官方首页：官方把它定义为 build LLM applications over your data 的 framework，并强调高层易用与低层可组合  
  https://developers.llamaindex.ai/python/framework/
- [E3] GitHub README：官方仓库定位它为用于构建 agentic AI over your enterprise data 的平台/框架  
  https://github.com/run-llama/llama_index
- [E4] GitHub Releases：官方 release 面用于核对已发布版本、发布时间与版本展示是否滞后于其他表面  
  https://github.com/run-llama/llama_index/releases
- [E5] VectorStoreIndex 文档：官方将其作为默认索引抽象，并解释其与 vector store 的关系  
  https://docs.llamaindex.ai/en/stable/module_guides/indexing/vector_store_index/
- [E6] RetrieverQueryEngine API / querying 文档：体现 retriever 与 response synthesizer 的组合边界  
  https://docs.llamaindex.ai/en/stable/api_reference/query_engine/retriever/
- [E7] Workflows 文档：官方事件驱动工作流与 agent workflow 入口，并提示独立 workflows 包可能快于 core 版本  
  https://docs.llamaindex.ai/en/stable/module_guides/workflow/
- [E8] StorageContext API：官方存储编排层，负责 docstore / index store / vector store / graph store 的组合  
  https://docs.llamaindex.ai/en/stable/api_reference/storage/storage_context/
- [E9] Response Synthesizers 文档：官方查询生成层，说明“如何答”是独立于“取什么”的边界  
  https://docs.llamaindex.ai/en/stable/module_guides/querying/response_synthesizers/
- [E10] ServiceContext -> Settings migration：官方明确 `Settings` 是新的全局、懒加载默认配置方式  
  https://docs.llamaindex.ai/en/stable/module_guides/supporting_modules/service_context_migration/
- [E11] Deprecated Terms：官方迁移表，把 `AgentRunner` / `AgentWorker` / `QueryPipeline` / `ServiceContext` 等旧概念导向新抽象  
  https://docs.llamaindex.ai/en/stable/changes/deprecated_terms/
- [E12] Workflows package docs：官方 workflows 站点，用于确认独立 package 与当前工作流/agent workflow 能力表面  
  https://llamaindex-workflows.readthedocs.io/

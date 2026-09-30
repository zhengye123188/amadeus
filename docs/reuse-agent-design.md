# 复用现成 Agent：Pi 科研扩展方案

调研日期：2026-09-30。以下保留最初的选型理由；v0.2 已实现 Pi CLI、Python MCP、科研记忆、实验适配与集成测试，具体当前行为见 [architecture.md](architecture.md) 和根目录 README。原 Python 运行时保留为 research-legacy；npm/PyPI 发布尚未执行。

## 决策建议

以 **Pi CLI + 科研扩展 + Python MCP 服务** 作为下一阶段方向。先复用完整 CLI，通过扩展接口接入自己的领域能力；需要独立品牌入口时，再使用 Pi SDK。优先依赖公开扩展接口，不复制内部实现，也不一开始维护大范围 fork。

理由是本项目目标为可交互的科研搭档和面试作品。终端绘制、模型流式协议、通用文件工具和会话恢复都是必要基础设施，但继续自行实现这些会挤占科研证据、实验管理和真实评测的投入。原型仍可作为工程对照，领域代码和测试保留。

## 核查的候选

| 基础项目 | 官方可复用接口 | 对本项目的判断 |
|---|---|---|
| Pi | 交互 CLI、TypeScript SDK、扩展、会话树、压缩、自定义工具、原生 MCP | 首选。先保留现成终端，再通过扩展研究上下文管理 |
| OpenCode | 插件、自定义工具、MCP、服务端 SDK、压缩钩子 | 若更希望在完整编码助手上加科研能力，是可行备选 |
| OpenHands Software Agent SDK | Python/TypeScript/REST API、工具、会话、workspace/Agent Server | 若必须坚持 Python 主运行时或强调远程执行，值得选择；需要结合其 CLI 做体验验证 |

上表后列是本项目的取舍判断，不是三个项目的性能或稳定性排名。没有对它们做相同任务的速度基准。

Pi 官方仓库现位于 [earendil-works/pi](https://github.com/earendil-works/pi)，旧 `pi-mono` 地址会跳转；当前 SDK 包名为 `@earendil-works/pi-coding-agent`。核查时主分支及 [npm latest 元数据](https://registry.npmjs.org/@earendil-works/pi-coding-agent/latest)均为 `0.99.1`、要求 Node `>=22.19.0`。现已安装并通过真实 Pi / 模拟模型的端到端集成验证；版本与依赖由 package-lock.json 固定。仓库采用 MIT 许可证，保留上游版权/许可说明，并明确 README 中哪些部分来自上游。

来源：[Pi SDK](https://pi.dev/docs/latest/sdk)、[Pi extensions](https://pi.dev/docs/latest/extensions)、[OpenCode plugins](https://opencode.ai/docs/plugins/)、[OpenCode SDK](https://opencode.ai/docs/sdk/)、[OpenHands SDK](https://github.com/OpenHands/software-agent-sdk)。

## 新架构

```mermaid
flowchart LR
    User[用户在终端自由对话] <--> Pi[Pi CLI / AgentSession]
    Pi <--> Ext[科研扩展：上下文与工具策略]
    Pi <--> MCP[Python 科研 MCP 服务]
    MCP <--> Evidence[文献索引与证据库]
    MCP <--> Jobs[实验快照与运行台账]
    Ext <--> MCP
```

用户仍可从论文、代码或失败日志开始；业务不设强制阶段。MCP 是工具连接协议，不负责决定科研步骤，下一工具由 Agent 根据当前问题与结果选择。

当前 Pi 官方版本支持 stdio / streamable HTTP MCP，工具可进入其工具事件处理链，因此 Python 服务无需被整体改写成 TypeScript。科研扩展使用 TypeScript，负责 `/papers`、`/evidence` 等界面能力及领域上下文。最小接入显式设置 MCP `exposure: "direct"`；当前默认暴露方式为 Codemode，不能把省略配置误当作直接工具调用。确有大量工具占用上下文的问题时，再评估动态工具暴露或 Codemode。未来改用 SDK 时，需显式加载 MCP 等内置扩展，不能假定 SDK 自动具备完整 CLI 配置。

来源：[Pi MCP](https://pi.dev/docs/latest/mcp)、[扩展工具与上下文接口](https://pi.dev/docs/latest/extensions)。

## 现有代码怎么处理

| 当前模块 | 后续处理 |
|---|---|
| `cli.py`、`providers.py`、`runtime.py` | 原型保留作对照，主入口逐步交给 Pi |
| `context.py` | 通用压缩由 Pi 接管，领域约束保留改为扩展策略 |
| `research.py` | 保留文献、PDF、GitHub、分块、检索和证据逻辑，通过 MCP 暴露 |
| `jobs.py` | 保留有界实验、快照和台账，经明确的执行策略接入 |
| `storage.py` | 保留来源、证据、chunk、实验数据；对话历史由 Pi 管理，避免两个会话真相来源 |
| `tools.py` | 通用文件功能优先复用 Pi；把已有权限、越界和冲突测试作为迁移约束 |
| `extensions.py` | embedding/Jev 可以保留为领域能力；现有 MCP 代码是客户端，需新增服务端适配器 |
| `tests/`、`evals/` | 保留领域和执行测试，新增真实 Pi/MCP 桥接与上下文压缩评测 |

迁移已加入 Schema、MCP 错误传播、取消/超时、生命周期和会话关联适配。后台实验由服务生命周期管理，不随单次工具调用结束销毁；同一 request_id 重连后不会自动启动第二次实验。

## “记忆”分三层

1. **会话记忆：**历史消息、分支、恢复和通用压缩。复用 Pi 的 `SessionManager`，不再维护一套竞争的对话状态。
2. **科研项目记忆：**研究目标、用户限制、paper/source ID、作者代码关联依据、commit、未验证假设、反例、实验参数/结果。保存在自己的结构化库，单独记录来源和状态，不能把模型推测直接升级为事实。
3. **模型上下文：**每轮只取当前相关的项目记录，附上可回查的原文/代码/产物 ID。长历史压缩时保留关键约束与引用指针，缺失时恢复原文，而非把全文一直塞进提示词。

Pi 的会话持久化和压缩不自动等于科研知识管理。可通过 `session_before_compact` 定制压缩结果；会话切换/分支也要重建正确的项目视图。重要证据原文仍独立保存，不依赖摘要承担唯一存储。

来源：[Pi 会话 SDK](https://pi.dev/docs/latest/sdk)、[压缩扩展接口](https://pi.dev/docs/latest/compaction)。

## 主打改进与面试价值

先选一个主线：**带可追溯证据的科研记忆与上下文管理**。例如长会话后仍能准确回答“这条改进假设的原文依据是什么、是否已验证、哪个 commit/数据集跑出了结果”，并保留先前的反例与算力限制。这是需要实验验证的工程假设，不声称科研新颖性或现成收益。

另一个实用点是论文到代码/实验的关联台账：记录来源、作者关联依据、commit、数据哈希、环境、参数和结果，区分仓库检查、smoke run、结果复现。检查已有记录后再决定是否重跑。

Jev 可作为相关性重排的可选实验项。先建立 BM25/hybrid 基线，比较检索质量、延迟和费用；不让相关性分数决定科学真实性或替代执行授权。

固定同一模型、相同工具集合、数据和预算，比较：

| 对照 | 用途 |
|---|---|
| 原版 Pi | 记录原生能力边界，不能把缺少科研工具的差距都归因于记忆策略 |
| Pi + 相同科研工具 | 检验领域工具本身带来的变化 |
| Pi + 科研工具 + 自定义记忆 | 主消融；隔离记忆策略的贡献 |
| 上一配置 + Jev | 仅在有账号与预算后测试重排增益 |

评价原文定位/引用正确率、约束保留率、事实/假设混淆率、重复实验率、任务完成率、延迟和费用。人工核验、公开样本数、重复运行和失败案例，不用当前容易满分的 toy 检索集证明优势。

## 执行边界与发布

Pi 默认并没有内置的完整权限系统，不能假定切换框架后自动拥有原项目的文件限制与审批。必须覆盖内置文件/bash 工具和 MCP 调用的策略，保留实验资源限制；需要强隔离时使用容器。MCP/工具提示里的只读标记只能作为线索，不能取代可信策略。来源：[Pi 官方权限说明](https://github.com/earendil-works/pi#permissions--containerization)。

发布可拆为 Pi 扩展（npm/GitHub）和 Python 科研 MCP 服务（PyPI）。PyPI 安装 Python 服务不代表已经安装 Node/Pi；现已实现 `research` 启动器，负责检测与组装运行环境，不重新实现 Agent 内核。当前 PyPI 发布配置草稿保留，尚未上传包或发布新版本。

## 最小迁移验收顺序

1. 把论文导入、检索、原文定位导出成 MCP 工具，连到真实 Pi 会话，验证由自然语言动态调用。
2. 接入证据持久化及项目约束，再测压缩、退出恢复与会话分支后的引用和约束保留。
3. 接入代码关联及受限实验，并验证审批拒绝、取消、超时和重连不会引发重复副作用。
4. 用固定任务集完成与默认 Pi 压缩的消融，再决定 Jev、Codemode 或多 Agent 是否值得加入。

这是软件迁移和验收的顺序，不是用户使用时必须经历的科研流程。

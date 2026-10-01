# Research CLI

**基于 Pi 的交互式科研 Agent：读论文、查开源代码、保留证据、提出假设、修改代码、运行受限实验。** 用户在终端自由对话并随时调整方向，模型根据问题和工具结果选择下一步。

v0.2 · macOS / Linux · 独立安装包自带运行环境 · MIT

复用 [Pi](https://github.com/earendil-works/pi) 的终端、模型接入、工具循环、会话树和基础压缩。项目自己的工作集中在**可追溯科研记忆、论文/代码/实验关联、工具权限和可重复评测**。Pi 锁定为 `0.99.1`，不复制或修改其源码。

> 独立安装包通过 GitHub Releases 分发；npm / PyPI 采用单独的发布流程。开发者发布步骤见 [发布指南](docs/pypi.md)。

## 独立安装包（无需开发环境）

独立安装器包含 Node、Python、Pi 和科研工具依赖，无需预装开发环境。一条命令自动选择 macOS / Linux 的 x64 / ARM64 安装包，下载并验证校验和后安装：

```bash
curl -fsSL https://github.com/zhengye123188/research-cli/releases/latest/download/install.sh | sh
"$HOME/.local/bin/research" configure
"$HOME/.local/bin/research"
```

`configure` 会隐藏密钥输入，并将 API 地址、模型和密钥保存在本机，后续终端无需重新 export。默认安装在用户目录，不需要 sudo，不依赖 nvm。也可从 [公开下载页面](https://github.com/zhengye123188/research-cli/releases/latest) 下载对应平台的 `.run` 文件，执行 `sh ~/Downloads/<安装包文件名>`；下载后可离线安装，无需登录 GitHub。平台选择、校验、更新和构建方法见 [独立安装指南](docs/standalone.md)。

## 在项目目录使用

安装后，把命令目录加入当前终端的 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

如果希望新打开的终端也能直接使用 `research`，将这行放入自己的 shell 配置；macOS 默认 zsh 使用 `~/.zshrc`。

在目标项目文件夹打开终端，直接输入 `research`；也可以先切换目录：

```bash
cd "/你的项目目录"
research
```

启动时的当前目录自动成为工作区，无须切换到 Research CLI 的安装目录。文件工具、科研记忆和实验都使用这个项目目录，科研数据保存在项目的 `.research/` 中；API 配置保存在用户目录，只需配置一次。`/research-status` 可查看当前工作区和项目统计。

在同一项目目录再次启动 `research --continue` 可继续最近会话；从其他目录启动时，也可以用 `research --workspace "/你的项目目录"` 显式指定工作区。

显式使用 `--session` 或 `--resume` 恢复其他项目的历史会话时，Pi 会采用该会话保存的工作区。可用 `/research-status` 核对当前项目；若要把历史上下文带到当前项目，可使用 `research --fork <会话文件>`。

## 快速开始

需要 Node ≥22.19 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。如果使用 nvm，先执行 `nvm use 22`。

```bash
git clone https://github.com/zhengye123188/research-cli.git
cd research-cli
npm ci
uv sync --frozen --all-extras
node bin/research.mjs doctor

# 交互 CLI；不需要额外全局安装 Pi
npm start
```

首次配置模型可以在 Pi 界面使用 `/login`、`/model`，也可以在本机设置 API key 后指定提供商和可用模型：

```bash
# OPENAI_API_KEY 通过本机终端或密码管理器设置，不提交到仓库
npm start -- --provider openai --model '你的可用模型 ID'
```

OpenAI 兼容端点也可以通过 `node bin/research.mjs configure` 保存配置。配置文件位于 `~/.config/research-cli/api.json`（支持 XDG_CONFIG_HOME），权限为 0600；环境变量优先。文件工具会拒绝访问这份凭据文件。

对于支持流式工具调用的 OpenAI 兼容服务：

```bash
export OPENAI_BASE_URL='https://你的服务地址/v1'
export RESEARCH_MODEL='你的模型 ID'
export RESEARCH_API=chat           # chat 或 responses；兼容端点默认 chat
npm start
```

自定义端点的上下文窗口默认 32768，可用 `RESEARCH_CONTEXT_WINDOW` 调整；自定义模型的价格未配置，Pi 显示的 `$0` **不代表真实费用为零**。`doctor` 只检查运行环境及密钥是否存在，不验证模型 API。`.env` 不会自动加载。

想直接使用 `research` 命令，可以把当前源码打包安装：

```bash
npm pack                       # 打印生成的 .tgz 文件名
npm install -g ./lelouch_021015-research-cli-0.2.0.tgz
research setup                 # 用 uv 安装随 npm 包携带的 Python 后端源码
research doctor
research --workspace /你的科研目录
```

`setup` 是显式安装步骤，无需等待 Python 包发布到 PyPI。全局安装版使用用户缓存中的独立 Python 环境。单独安装 Python wheel 提供 `research-mcp` 和历史原型 `research-legacy`，交互式主入口 `research` 由 npm 包提供。

## 交互示例

```text
调研近三年检索重排的论文，先查 arXiv，再找原文提到的开源代码。
先不继续找论文。导入 papers/baseline.pdf，给我看这个结论的原文依据。
记住这个项目只用 CPU。这个改进目前只是待验证假设。
检查本地 src/ranker.py，结合论文提出最小改动和验证方案。
查看已有实验和失败原因，避免重复运行同一个请求。
```

上面是建议输入，不是已完成的真实科研结果。

| 操作 | 入口 |
|---|---|
| 查看科研记忆、证据、实验 | `/memory`、`/evidence`、`/jobs` |
| 查看项目统计、MCP 状态 | `/research-status`、`/mcp` |
| 压缩、会话树、新会话 | Pi 的 `/compact`、`/tree`、`/new` |
| 重启继续 | `research --continue`，或 `--session <路径或 ID>` |
| 从旧会话分支 | `research --fork <路径或 ID>` |
| 停止当前 Agent 操作 | Pi 的 Esc / Ctrl-C；已启动实验需明确取消 |
| 保存/修改科研记录、取消实验 | 自然语言调用相应工具；无固定科研阶段 |

主程序复用 Pi TUI。科研命令与旧 Python CLI 的命令不完全相同；旧版说明归档在 [legacy-cli.md](docs/legacy-cli.md)。

## 已实现能力

| 领域 | 实现与边界 |
|---|---|
| 文献发现 | Crossref、arXiv 年份范围检索；返回 metadata/abstract 层级，不声称穷尽 |
| 原文 | 本地 PDF/UTF-8 导入、按 ID 下载 arXiv PDF；来源哈希、页码和 chunk 定位；无 OCR |
| 代码关联 | GitHub 候选检索、README/文件读取、固定 commit、原文链接证据；不自动认证作者身份 |
| 检索 | BM25；可选 embeddings + RRF hybrid search；可选 Jev 相关性重排 |
| 证据 | 引文必须是原文 chunk 的精确子串；引文存在与科学结论成立分别标记 |
| 科研记忆 | 约束、假设、文献报告、实验观察、负结果、决策；引用 ID 校验、修订历史和冲突检测 |
| 上下文 | 每次模型请求注入相关项目记录；约束优先，超出预算明确给出遗漏数；压缩附证据快照 |
| 实验 | 快照、哈希清单、后台任务、日志、超时、取消、资源限制、稳定 request_id 去重 |
| 工程 | 原生 MCP、Schema 校验、审批、一次性授权、结构化错误、审计记录、真实 Pi 集成测试 |

项目记忆在同一 workspace 的不同会话/分支之间共享，并记录来源 session ID。分支不会回滚数据库，过期约束需要显式退役。对话历史由 Pi 管理，科研记录位于 `.research/state.sqlite3`。

## 权限与实验

默认 `--permission ask --execution disabled`。读文件与工具均受边界检查；写入需批准。非交互模式无法弹窗时拒绝需审批的操作。

```bash
# 自动允许工作区/科研记录写入，实验仍关闭
research --permission workspace-write

# 使用已经准备好的 Docker 镜像；不会自动拉镜像或退回本地执行
research --execution docker

# 明确选择未隔离的本机进程，交互时仍需执行审批
research --execution local

# 自动化实验需要显式授权执行；只读模式仍优先拒绝
research --permission workspace-write --execution docker --approve-experiments
```

Pi 的普通 bash/`!` 命令入口在本产品中关闭，实验统一走 `run_experiment`。Docker 后端无网络、只读根目录、1 CPU、1 GiB 内存、128 进程；工作快照上限 50 MB/5000 文件。`local` 不是安全沙箱。Pi、扩展和 MCP 服务本身都是可信本地程序；需要隔离整个 Agent 时应把整个程序放进容器。

实验返回 job ID，不阻塞聊天；退出、重载或切换导致 MCP 服务关闭时会取消它拥有的实验。意外退出留下的作业标记 `interrupted_unknown`，不会自动认领旧 PID 或盲目重跑。重试同一实验应复用 `request_id`；修改参数需使用新 ID。

`--max-turns 32 --max-seconds 600` 提供每次交互的模型步数/时间预算，不是支付硬限额。`--offline` 只关闭后端网络工具，模型连接仍可能联网。

## 可选配置

```bash
cp config.example.toml research.toml
research --config research.toml
```

文件用于 Python 工具层的超时、实验镜像、输出上限和 embedding 设置；Pi 模型用 `/model`、CLI 参数和环境变量配置。权限、执行模式和 offline 以启动参数为准。不会自动加载工作目录中的第三方扩展、MCP 配置或 AGENTS.md；额外扩展需显式 `--extension` 加载，并承担其本机代码权限。

Embedding 需要显式配置模型；Jev 需要安装 Python `jev` extra 并设置 `TYPESAFE_API_KEY`。这两类付费工具要求审批，不纳入 Pi 主模型 token 费用。源码安装可用 `uv sync --frozen --all-extras`。MCP 服务端也可独立使用：

```bash
uv run research-mcp --workspace /你的科研目录 --permission read-only
```

## 测试与评测

```bash
npm ci
uv sync --frozen --all-extras
npm run check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
npm test
npm run eval:memory
uv build --no-sources
npm pack --dry-run
```

Python 测试覆盖领域逻辑、真实 stdio MCP、执行与旧原型；TypeScript 集成测试启动**真实 Pi + Python MCP + 本机模拟模型服务**，覆盖证据、权限、压缩、恢复、分支和实验。这些不需要模型密钥，也不等同于真实模型能力评估。

`npm run eval:memory` 是可重复的机制验证。`npm run eval:memory -- --live` 才会使用配置的模型进行付费对照，比较相同工具、数据、模型和预算下的 `--memory off/on`。默认输出 `evals/results/local-memory.json`，不提交本机结果。详见 [评测说明](evals/README.md) 和 [验证记录](docs/validation.md)。

## 架构与限制

项目通过持久化科研记录、上下文注入和证据快照，在长对话压缩与会话恢复后保留科研约束、原文证据和实验状态。模块职责与代码映射见 [architecture.md](docs/architecture.md)。

当前没有多 Agent、远程/GPU 作业、自动依赖安装、OCR 或论文真实复现保证；检索与向量存储适用于小规模项目。Jev 与真实模型收益必须实测，本项目不宣称科研新颖性或未经验证的性能提升。

上游许可与归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。贡献与发布见 [CONTRIBUTING.md](CONTRIBUTING.md)、[发布指南](docs/pypi.md)。

# Research CLI

基于 [Pi](https://github.com/earendil-works/pi) 的交互式科研 Agent。在项目目录打开终端，直接对话、查论文、检查代码、保存证据和运行受限实验，由 Agent 根据当前问题选择工具。

**v0.2.0 · macOS / Linux · MIT**

[npm 包](https://www.npmjs.com/package/@lelouch_021015/research-cli) · [独立安装包](https://github.com/zhengye123188/research-cli/releases/latest) · [架构](docs/architecture.md)

## 安装

### npm

需要 Node ≥22.19 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。Pi 会作为依赖安装，不需要单独安装。

```bash
npm install -g @lelouch_021015/research-cli
research setup
research configure
cd "/你的项目目录"
research
```

`research setup` 安装包内 Python 后端源码到独立缓存环境，不依赖后端发布到 PyPI。

### 自带运行环境的独立安装包

无需预装 Node、Python、uv 或 Pi，自动识别 macOS / Linux 的 x64 / ARM64：

```bash
curl -fsSL https://github.com/zhengye123188/research-cli/releases/latest/download/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
research configure
cd "/你的项目目录"
research
```

默认安装在用户目录，无需 sudo。若要在新终端直接使用 `research`，将上面的 PATH 设置加入 shell 配置。也可在 [Releases](https://github.com/zhengye123188/research-cli/releases/latest) 下载 `.run` 文件后执行 `sh <安装包路径>`，下载后可以离线安装。平台要求、校验和更新方法见 [独立安装指南](docs/standalone.md)。

## 配置 API

运行 `research configure`，按提示填写 API 地址、账号可用的模型 ID、协议和密钥。程序提供 DeepSeek 地址及 `chat` 协议作为默认值，也支持其他 OpenAI 兼容端点；使用自己账号可用的模型。

密钥输入不回显，配置保存到 `~/.config/research-cli/api.json`，文件权限为 `0600`，可在不同项目间共用。环境变量优先于保存的配置，`.env` 不会自动加载。

```bash
research doctor    # 检查程序和后端环境，不调用模型 API
research --version
```

其他模型提供商可在 Pi 界面使用 `/login`、`/model`。`doctor` 不验证密钥或模型权限；自定义模型价格未配置时，界面显示 `$0` 不代表实际费用为零。

## 在项目目录使用

启动目录就是工作区。文件操作、科研记忆与实验记录围绕当前项目，项目数据保存在 `.research/` 中，API 配置属于用户。

```bash
cd "/你的项目目录"
research
research --continue                       # 继续该项目最近的会话
research --workspace "/另一个项目目录"       # 显式指定工作区
```

显式恢复 `--session` 或 `--resume` 时，Pi 使用历史会话保存的工作区；可用 `/research-status` 核对。`research --fork <会话文件>` 可把历史上下文带入当前项目。

可以这样对话：

```text
调研近三年检索重排的论文，优先找原文提到的开源代码。
导入 papers/baseline.pdf，给我看这个结论的原文依据。
记住这个项目只使用 CPU，这个改进目前是待验证假设。
检查 src/ranker.py，提出最小改动及验证方案。
查看已有实验和失败原因，避免重复运行。
```

| 命令 | 用途 |
|---|---|
| `/research-status`、`/mcp` | 工作区、项目统计与工具连接 |
| `/memory`、`/evidence`、`/jobs` | 科研记忆、证据与实验记录 |
| `/compact`、`/tree`、`/new` | 压缩上下文、查看会话树、开启新会话 |

## 功能

| 能力 | 当前实现 |
|---|---|
| 文献与代码 | Crossref / arXiv 检索，GitHub 候选检索、文件读取与固定 commit |
| 原文与证据 | PDF / 文本导入、arXiv PDF 下载，来源哈希、页码、分块与精确引文 |
| 检索 | BM25，可选 embeddings + RRF 混合检索及 Jev 重排 |
| 项目记忆 | 约束、假设、负结果、决策、修订历史和冲突检测 |
| 上下文 | 每轮注入相关项目记录，压缩时保留证据快照 |
| 实验 | 工作快照、后台任务、日志、超时、取消、资源限制及请求去重 |
| 工具协议 | Python stdio MCP、参数校验、审批及审计记录 |

Pi 提供终端界面、模型接入、工具循环和会话管理；本项目提供科研工具、证据记忆与权限策略。对话历史由 Pi 管理，科研记录位于项目的 `.research/state.sqlite3`，同一项目的不同会话共享记录。

## 权限与可选配置

默认写入需要批准，实验执行关闭。普通 shell / `!` 入口关闭，实验通过 `run_experiment` 工具执行。

```bash
research --permission read-only        # 只读业务工具
research --permission workspace-write  # 自动允许工作区及科研记录写入
research --execution docker            # 使用已准备的 Docker 镜像运行实验
research --execution local             # 允许本机实验，仍需审批；不提供进程隔离
```

Docker 只隔离实验进程。退出或关闭 MCP 服务会取消它拥有的实验；异常退出后的未知状态需检查，不会自动重跑。其他限制见 [执行与数据边界](SECURITY.md)。

高级工具配置可复制 [配置示例](config.example.toml)，通过 `research --config research.toml` 显式加载。Embedding 需要配置模型；npm 安装可用 `research setup --jev` 添加 Jev 依赖，并在本机设置 `TYPESAFE_API_KEY`。独立安装包已包含 Jev 依赖；付费工具调用仍需审批。

## 开发与文档

```bash
git clone https://github.com/zhengye123188/research-cli.git
cd research-cli
npm ci
uv sync --frozen --all-extras
node bin/research.mjs configure
npm start
```

[贡献与检查命令](CONTRIBUTING.md) · [架构](docs/architecture.md) · [发布指南](docs/pypi.md) · [评测方法](evals/README.md) · [验证记录](docs/validation.md) · [第三方许可](THIRD_PARTY_NOTICES.md)

当前支持 macOS / Linux，不支持 Windows、Alpine/musl、OCR、远程/GPU 作业或多 Agent。检索适用于小规模项目，精确引文校验不等于科学结论验证。工程测试使用真实 Pi/MCP 和模拟模型，不代表真实模型科研效果或论文复现已验证。

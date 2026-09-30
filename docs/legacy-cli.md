# Python 原型（v0.1 历史说明）

此文档归档迁移前行为。当前入口、安装和配置请看根目录 README；旧运行时使用 `research-legacy`。下面的发布说明仅是当时的草稿，不代表包已发布。

# ResearchCLI

一个可以持续对话、读论文、查代码、修改文件和运行小实验的终端科研 Agent。模型根据当前问题与工具结果选择下一步，用户可以停止、追问或切换任务。

**v0.1 开发版 · Python 3.10+ · macOS / Linux · MIT。** 研究阶段不是固定工作流。面试讲解见 [架构](https://github.com/zhengye123188/research-cli/blob/main/docs/architecture.md)。PyPI 首次发布尚待账号授权；安装与发布状态见下面的说明。

## 一条命令安装 CLI

现在即可从 GitHub 安装（需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)）：

```bash
uv tool install --python 3.12 git+https://github.com/zhengye123188/research-cli.git
```

安装后进入你的研究目录，直接运行 `research-legacy --demo`，不需要 `uv run` 或克隆源码。模型模式用 `research`，API 环境变量的配置相同。若提示找不到 `research`，执行 `uv tool update-shell` 后重新打开终端。

**只有首次 PyPI 发布成功后**，才可以直接按包名安装：

```bash
uv tool install --python 3.12 research-terminal
```

包名为 `research-terminal`，终端命令为 `research`。发布后也支持 `pipx install research-terminal`，或在自己的虚拟环境中使用 `python -m pip install research-terminal`。可选扩展安装为 `uv tool install 'research-terminal[mcp,jev]'`。维护者配置步骤见 [PyPI 发布指南](https://github.com/zhengye123188/research-cli/blob/main/docs/pypi.md)。

## 从源码运行与开发

需要 Python 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。首次使用先下载仓库，再安装启动：

```bash
git clone https://github.com/zhengye123188/research-cli.git
cd research-cli
uv sync --frozen --all-extras
uv run research-legacy --demo
```

`--demo` 不需要 API key，是明确标注的确定性工具演示，没有模型推理。可以输入：

```text
列出文件
读取 @README.md
/import examples/retrieval_lab/README.md
search 实验
/sessions
/help
/exit
```

真实模型使用环境变量配置，密钥只保留在本机：

```bash
export RESEARCH_MODEL='填入账号可用的模型名'
# 在本机终端安全设置 OPENAI_API_KEY；不要提交到 Git
uv run research
```

默认使用 OpenAI Responses API。对于支持流式工具调用的 Chat Completions 兼容服务：

```bash
export OPENAI_BASE_URL='https://你的服务地址/v1'
uv run research-legacy --api chat --model '你的模型名'
```

端点必须支持所用参数；不同兼容服务不保证完全兼容。程序没有默认付费模型，也不内置密钥。`uv run research-legacy doctor` 检查配置，只显示密钥是否存在。高级配置：

```bash
cp config.example.toml research.toml
# 编辑 research.toml 中的非秘密配置
uv run research-legacy --config research.toml
```

只加载显式传入的配置。`research.toml`、`.env*`、`.research/` 和 `.venv/` 已忽略。用 `--workspace /path/to/research` 指定研究目录。第三方代码请自行下载并审阅后放入目录；本版没有自动 clone 或依赖安装器。

## 交互方式

以下是建议输入，不是已经完成的真实模型运行记录：

```text
you › 调研近三年检索重排的工作，优先检查原文提到的 GitHub 代码。
you › 先不做综述，读一下本地 src/model.py，解释评分函数。
you › 结合我导入的论文，找这个假设的反例，每条给出原文位置。
you › 先提出改进和验证方案，不运行实验。
```

文本流式显示，工具有独立事件。工具错误交回模型，允许它调整参数或方案。写文件、执行命令和付费扩展按策略请求批准。

| 操作 | 命令 / 按键 |
|---|---|
| 提交 / 换行 / 历史 | Enter / Alt-Enter / 上下箭头 |
| 停止当前轮 | Esc、Ctrl-C 或 `/stop` |
| 立即改变方向 | 先 `/stop`，再输入新要求 |
| 执行中继续输入 | 排队为下一轮，不追溯更改正在执行的动作 |
| 会话 | `/new`、`/sessions`、`/resume SESSION_ID` |
| 重启后继续 | `uv run research-legacy --resume last` |
| 上下文和固定约束 | `/context`、`/compact`、`/remember compute 只使用 CPU` |
| 资料和证据 | `/import '论文路径.pdf'`、`/evidence` |
| 能力和任务 | `/tools`、`/skills`、`/jobs`、`/cancel JOB_ID` |
| 改动与日志 | `/diff`、`/permissions`、`/model`、`/cost`、`/trace` |
| 退出 | `/exit` 或 Ctrl-D，会停止本 CLI 拥有的实验 |

`@path` 在 demo 中读取文件，在真实模型模式下由模型理解并调用工具。脚本入口与交互入口共用内核：

```bash
uv run research-legacy --demo exec '读取 @README.md' --json
uv run research-legacy --permission read-only exec '解释本地文件结构' --json
```

`exec` 无交互审批，默认拒绝需要确认的操作；显式 `--permission workspace-write` 允许文件写入。退出码 0 表示轮次完成，1 表示失败/停止，2 表示配置错误。轮次完成不等于所有工具成功，要检查 JSONL 工具结果。

## 已实现能力

| 能力 | 实现与范围 |
|---|---|
| Agent loop | asyncio 动态工具循环，仅完整模型响应可触发工具 |
| 模型 | Responses + Chat Completions，原生 reasoning 输出保留用于续聊，不展示隐藏思维链 |
| 状态 | SQLite 会话/事件/证据/实验，中断补记未知结果，不自动重放 |
| 上下文 | 字符预算、旧轮次抽取压缩、项目便签、长结果落盘和取回 |
| 文件 | 有边界的读取和字面搜索、SHA256 冲突检查、精确替换、备份、diff |
| 文献 | Crossref 按年检索；本地 PDF/文本；按 arXiv ID 取 PDF；页码和分块 |
| GitHub | README/许可证/固定 commit 目录与文本；从资料中提取显式代码链接 |
| 证据 | claim–quote–source–position；校验引用子串，语义支持仍需审查 |
| RAG | BM25；可选 embeddings / dense / RRF；索引区分端点与模型 |
| Skills / MCP | 三个按需科研方法；stdio 工具发现、校验、审批、超时和本地示例 |
| Jev | TypeSafe Score 相关性重排，记录模型和用量，不充当科学正确性裁判 |
| 实验 | 快照、hash 清单、异步任务、输出限制、超时和取消；Docker 或显式 local |

主模型预算与 embeddings/Jev/MCP 费用分开，不构成总账单上限。价格缺失时成本为 unknown。token 预检查使用字符估计，实际用量和账单以供应商为准。

## 实验与扩展

自包含例子不用 API 或 GPU：

```bash
uv run python examples/retrieval_lab/run.py --output /tmp/retrieval-metrics.json
```

输出逐条排名、Recall@3、MRR@10、数据和源码哈希。首次实测的 8 条 test 查询中，overlap 与 BM25 两个指标均为 1.0；数据过于简单，未显示质量提升。这是执行接口验证，不是论文复现。见 [实验说明](https://github.com/zhengye123188/research-cli/blob/main/examples/retrieval_lab/README.md)、[原始结果](https://github.com/zhengye123188/research-cli/blob/main/evals/results/retrieval-smoke.json) 和 [评测计划](https://github.com/zhengye123188/research-cli/blob/main/evals/README.md)。

启用容器前，自行安装 Docker 并准备可信镜像：

```bash
docker pull python:3.11-slim
uv run research-legacy --execution docker
```

容器无网络、根文件系统只读、1 CPU / 1 GB 内存、有进程数量限制，只挂载实验目录的复制品。不自动下载镜像；复跑建议使用镜像 digest。`--execution local` 是不隔离的主机执行，只用于可信代码，仍需逐次批准。默认禁用执行。

- Embeddings：配置 `embedding_model`，模型可申请 `index_embeddings` / `hybrid_search`。
- Jev：安装 `jev` extra，本机设置 `TYPESAFE_API_KEY`。模型可申请 `jev_rerank`，使用 [TypeSafe SDK](https://docs.typesafe.ai/sdk/python) 的有序 Score rubric，相关性量表为 0–4。缺少 key 时明确失败。
- MCP：安装 `mcp` extra，按 `config.example.toml` 配置可信 server；示例在 `examples/mcp_server.py`。配置代表允许启动本地进程，工具调用仍需批准。

## 验证与边界

```bash
uv sync --frozen --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

已做工程测试、真实 SDK 的模拟 HTTP 协议测试、本地 MCP stdio、中文/多行伪终端、实际本地子进程和合成检索实验。CI 将在推送后运行。

没有真实模型/embedding/TypeSafe key，因此不声称真实模型端到端通过或 Jev 有收益。开发机没有 Docker，未做容器实机验证。本项目也不是 Claude Code/Codex CLI 的功能等价实现。

当前限制：Crossref 不是完整 CS 论文搜索；PDF 无 OCR，公式/表格可能丢失；代码归属和新颖性不自动认证；无自动依赖安装、任意网站下载、多 Agent、GPU/远程作业、守护进程或 Windows 支持。压缩有损，重要约束需 `/remember`；向量索引是小规模 SQLite 扫描。崩溃前的实验标记为未知，需要人工检查。

`.research/` 的会话、历史和日志可能含科研秘密，不要上传。排除规则不能识别所有秘密，使用独立工作区并先审阅材料。见 [SECURITY.md](https://github.com/zhengye123188/research-cli/blob/main/SECURITY.md)。

## 代码导览

```text
src/research_cli/
  cli.py          输入、流式显示、审批、命令和队列
  runtime.py      动态工具循环、预算、取消恢复
  providers.py    模型协议与离线演示
  tools.py        校验、权限、文件、按需 skills
  research.py     文献、GitHub、分块、BM25、证据
  jobs.py         快照和实验
  extensions.py   embeddings / Jev / MCP
  storage.py      SQLite、事件、产物
  context.py      上下文与抽取压缩
```

贡献见 [CONTRIBUTING.md](https://github.com/zhengye123188/research-cli/blob/main/CONTRIBUTING.md)。历史设计仍保留；实际状态以本 README 和开发任务清单为准。

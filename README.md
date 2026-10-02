# Research CLI

基于 [Pi](https://github.com/earendil-works/pi) 的交互式科研 Agent。在项目目录打开终端，直接讨论论文、检查代码、整理证据和验证改进，由 Agent 根据当前问题选择工具。用户可以从任意问题开始、继续已有记录或随时转向。

**v0.4.0 · macOS / Linux · MIT**

[npm 包](https://www.npmjs.com/package/@lelouch_021015/research-cli) · [独立安装包](https://github.com/zhengye123188/research-cli/releases/latest) · [版本说明](docs/releases/v0.4.0.md) · [架构](docs/architecture.md)

GitHub 已发布 **v0.4.0** 独立安装包，覆盖 macOS/Linux ARM64 与 x64，四个平台均通过原生构建和安装检查。安装后用 `research --version` 核对版本。新版 Pi 原生工具包和包管理能力详见 [版本说明](docs/releases/v0.4.0.md)。

## 安装

### 自带运行环境的独立安装包

无需预装 Node、Python、uv 或 Pi，自动识别 macOS / Linux 的 x64 / ARM64：

```bash
curl -fsSL https://github.com/zhengye123188/research-cli/releases/latest/download/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
research configure
cd "/你的项目目录"
research
```

默认安装在用户目录，无需 sudo。将 PATH 设置加入自己的 shell 配置后，新终端也能直接运行 `research`。也可从 [Releases](https://github.com/zhengye123188/research-cli/releases/latest) 下载 `.run` 文件，执行 `sh <安装包路径>`；下载完成后可以离线安装。平台要求、校验和更新见 [独立安装指南](docs/standalone.md)。

### npm

npm **v0.4.0** 已发布，与独立安装器提供相同的 Pi 包复用和包管理能力。

需要 Node ≥22.19 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。Pi 作为依赖安装，无需单独安装：

```bash
npm install -g @lelouch_021015/research-cli
research setup
research configure
cd "/你的项目目录"
research
```

`research setup` 将包内 Python 后端安装到独立缓存环境，不依赖后端发布到 PyPI。更新时重新运行 `npm install -g @lelouch_021015/research-cli@latest` 和 `research setup`，再用 `research --version` 核对。

## 配置 API

运行 `research configure`，填写 API 地址、账号可用的模型 ID、协议和密钥。程序提供 DeepSeek 地址及 `chat` 协议作为默认值，也支持其他 OpenAI 兼容端点。

密钥输入不回显，配置保存到 `~/.config/research-cli/api.json`，权限为 `0600`，可在不同项目间共用。环境变量优先，`.env` 不会自动加载。

```bash
research doctor               # 检查运行环境，不调用模型 API
research doctor --check-api   # 显式 GET /models，不生成文本
research --version
```

`--check-api` 检查端点访问及模型列表，无法证明生成、推理、图片或工具调用兼容性；没有 `/models` 的端点会提示未验证。其他模型提供商可在 Pi 界面使用 `/login`、`/model`。

v0.3.0 支持 `--model-profile model-profile.json` 配置上下文、输出上限、推理/图片能力声明和每百万 token 的美元价格。价格未知保留为未知；Pi 显示 `$0` 不代表实际免费。配置示例及外部 MCP 接入见 [配置指南](docs/configuration.md)。

## 在项目目录使用

启动目录就是工作区。项目科研数据保存在 `.research/`，API 配置属于用户。v0.4.0 将 Pi 会话和包安装放在独立的 `~/.local/share/research-cli/pi-packages/`，避免加载其他 Pi 安装的包配置。旧 `~/.pi/agent` 会话可通过 `research --session /旧会话路径.jsonl` 恢复，也可明确设置 `PI_CODING_AGENT_DIR`。[包与会话说明](docs/pi-packages.md)

```bash
cd "/你的项目目录"
research
research --continue                       # 继续该项目最近的会话
research --workspace "/另一个项目目录"       # 显式指定工作区
```

显式恢复 `--session` 或 `--resume` 时，Pi 使用历史会话保存的工作区；可用 `/research-status` 核对。`research --fork <会话文件>` 可把历史上下文带入当前项目。

可以这样对话：

```text
调研近三年的检索重排论文，优先找原文提到的代码，保留仓库版本依据。
将 papers/baseline.pdf 关联到已有论文，比较这些论文的数据和评价协议。
记住项目只使用 CPU；这个改进目前是推断，先列出可推翻它的条件。
为 src/ranker.py 建立检查点，说明改动，再运行项目已有测试。
查看已有实验，用相同数据和协议比较基线与候选方案，保留失败结果。
导出比较报告，并告诉我哪些判断仍需人工审查。
```

| 命令 | 用途 |
| --- | --- |
| `/research-status`、`/mcp` | 工作区、项目统计与工具连接 |
| `/memory`、`/evidence`、`/jobs` | 科研记忆、证据与实验记录 |
| `/review-memory mem_...` | 用户查看当前记忆修订后明确确认或要求修改 |
| `/usage` | 模型用量、已知费用估计与独立付费工具记录 |
| `/compact`、`/tree`、`/new` | 压缩上下文、查看会话树、开启新会话 |

## 能力

| 能力 | 实现 |
| --- | --- |
| 文献与代码 | Crossref / arXiv、GitHub 候选检索、固定 commit 与文件哈希 |
| 网页与技术文档 | Pi 原生 `pi-web-access` 搜索/读取网页；Context7 查询库文档和示例 |
| 论文身份 | DOI 规范化、arXiv 版本关联、全文显式关联；标题相似不触发合并 |
| 原文与检索 | `pi-docparser` 本地 PDF 提取、文本导入、来源哈希、页码与精确引文；BM25，可选 embeddings/RRF 和 Jev |
| 论文比较 | 研究问题、方法、假设、数据、评价与限制；区分文献报告和推断，导出 Markdown/JSON/BibTeX |
| 复现记录 | 固定仓库、准备缺口、源码/数据/协议/命令对应及目标指标；关联材料不自动认定作者身份 |
| 项目记忆 | 约束、假设、负结果、决策和修订；支持/反驳需要明确条件与对应证据，人工确认单独记录 |
| 结构化实验 | 数据哈希、划分、协议、seed、参数、指标和产物；基线/候选比较、多次运行的描述统计与报告 |
| 持续任务 | 可选独立 worker、跨 CLI 会话查询与取消；显式从已结束任务的保存文件发起新恢复运行 |
| 代码验证 | 项目搜索与 Python 符号检查、Git diff、选定文件检查点、冲突检查回退、项目原目录测试/构建 |
| 配置与维护 | 模型 profile、显式外部 MCP/技能/项目指令、软预算、用量记录、数据库迁移和校验备份 |

默认联网配置提供 **53 个科研 MCP 工具 + 3 个 Pi 文件工具（read/write/edit）+ 6 个 Pi 包工具**，合计 62 个。配置 embeddings 后增加 2 个工具；离线模式移除联网包工具，外部 MCP 和用户安装的包按工具白名单增加。Jev 工具默认可发现，调用需要依赖、账号和审批。

PDF 解析底层已改用 `pi-docparser`，其原生文档工具不重复暴露；导入与证据保存仍通过科研 MCP。科研记忆的证据、作业、修订和人工确认关系，以及实验数据/协议/指标校验，保留项目自身实现。包审查、替换理由与完整工具列表见 [Pi 包复用指南](docs/pi-packages.md)。

```bash
npm start -- packages list             # 源码：查看三个内置包
research packages list                # 查看内置及用户包
research packages install npm:包名@固定版本 --policy ./package-policy.json
research --package-config ./packages.json
```

包管理复用 Pi 的公开安装器。新包不提供 policy 时只安装、不启用；启用时明确选择扩展文件、工具名和作用分类。当前支持工具与 skills，完整的插件命令、模型提供商和任意生命周期 hook 需要单独适配。Context7 密钥可通过 `CONTEXT7_API_KEY` 设置；网页供应商和配额独立于主模型 API。

Pi 提供终端、模型接入、工具循环和会话管理，本项目通过扩展提供科研能力与权限。科研记录在 `.research/state.sqlite3`，同一项目的不同会话共享；会话分支不会回滚数据库。

## 权限、执行与预算

默认 `ask`，业务写入需批准，执行关闭。普通 shell / `!` 入口关闭。实验使用快照，项目测试/构建可明确批准在原目录执行，两者都受执行权限控制。

```bash
research --permission read-only
research --permission workspace-write
research --execution docker --config research.toml
research --execution local            # 宿主执行，没有进程隔离
research --max-turns 32 --max-seconds 600 --max-tokens 60000
```

`--max-cost-usd` 需要配置全部四类 token 价格。token 和费用是请求完成后检查的软预算，进行中的请求可能超出；embeddings、Jev 和外部 MCP 的费用不包含在主模型费用预算内。`/usage` 记录未知项，不能替代供应商账单。

前台作业随拥有它的 MCP 服务关闭而取消。`detached: true` 的实验交给独立认证 worker，CLI 退出后可以继续；默认单次实验上限仍为 600 秒，长任务需要显式提高后端 `max_job_seconds` 和调用超时。身份无法确认时保留 `interrupted_unknown`，不按旧 PID 取消，也不自动重跑。Docker CPU、内存及 GPU 参数可配置；GPU 路径尚未实机验证。[实验说明](docs/experiments.md)

项目扩展、MCP、skills 和 `AGENTS.md` 不会自动加载。使用包 policy、`--package-config`、`--mcp-config`、`--skill`、`--instructions` 明确选择；外部工具必须声明每个允许工具的作用分类。这些代码仍具有宿主权限。[安全边界](SECURITY.md)

高级后端配置见 [config.example.toml](config.example.toml)。npm 安装可用 `research setup --jev` 添加 Jev 依赖；独立包已包含依赖，账号密钥需在本机设置。付费检索工具仍需批准。

## 备份与更新

```bash
research project info
research project backup
research project restore /备份路径/project.zip --workspace /新的工作区
```

备份包含科研数据库、产物、任务文件及已有用量账本；不包含用户 API 配置、Pi 会话或整个原始项目目录。恢复前校验文件与兼容数据库结构，在暂存区完成迁移，再安装到没有 `.research` 的工作区；已有项目数据不会被覆盖。运行中或身份未确认的独立任务会阻止备份。[项目数据说明](docs/project-data.md)

## 开发与验证

```bash
git clone https://github.com/zhengye123188/research-cli.git
cd research-cli
npm ci
uv sync --frozen --all-extras
node bin/research.mjs configure
npm start
```

[贡献与检查命令](CONTRIBUTING.md) · [架构](docs/architecture.md) · [配置](docs/configuration.md) · [Pi 包](docs/pi-packages.md) · [论文比较](docs/research-map.md) · [证据与代码](docs/claims-and-code.md) · [发布](docs/pypi.md) · [评测](evals/README.md) · [验证记录](docs/validation.md) · [第三方许可](THIRD_PARTY_NOTICES.md)

现阶段以工程测试保证软件机制可靠；公开 CPU 案例是可选开发示例，真实科研评测在开展实际任务后另行设计。文件保护、来源和产物校验不能证明科学结论、作者代码身份或完整论文复现，模拟模型测试也不能说明真实模型科研效果。检索适用于小规模项目；OCR、Windows、Alpine/musl、SSH/集群远程作业和多 Agent 尚未支持，GPU 参数未实机验证。

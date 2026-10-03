# 验证记录

更新日期：2026-10-03。开发环境为 macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；依赖由 `package-lock.json` 和 `uv.lock` 固定。

## 像素界面：源码更新，尚未发布安装包

- Python **194 项通过**；最终 Node/TypeScript **96 项通过、2 项可选 OCR 测试跳过**。这次本地没有设置 `RESEARCH_OCR_TEST_DATA`；已有 v0.5.0 原生 OCR 验证见下方。类型检查、Ruff/格式、版本同步和 diff 检查通过。
- 真实 PTY 验证像素头部、普通终端字符头像及关闭、中文/空格工作区、120→54→120 列缩放、模型选择与 Esc、中文提示和 Ctrl+D。`/new`、`/reload` 后仍使用像素配色；切换原主题后重载保持原主题。恢复选择器的 Ctrl+N 命名过滤及取消通过。
- 实际 SettingsManager 保存模型/主题设置、重新加载后，Research 静默启动和默认配色仍有效，启动不写品牌覆盖值。没有原 Pi 欢迎页闪现；命令补全、光标和编辑行为继续由公开 Pi 组件处理。
- RPC 与 JSON 模式实际运行 Pi 和本地模拟 API，输出保持 JSON，不包含 ANSI 或图片协议。界面状态使用真实模型、上下文、Git 分支和扩展状态，未知上下文显示 `ctx ?`。
- 最终源码 npm tarball 在独立临时目录实装，`setup`、`doctor`、四个内置包、科研扩展、原生 PDF 导入以及以上整套 PTY 验证通过。PNG、调色板 JSON、两份主题和 SDK 交互入口全部在打包清单中；独立构建从同一 npm 包整体提取文件。
- 本次模型响应来自本机 HTTP fixture，仅用于工程验证；未使用用户密钥或付费模型。没有修改用户全局安装，也没有发布新的 npm 版本或 GitHub Release。现有公开 v0.5.0 安装包仍不包含这次界面更新。

## v0.5.0：按工具职责协作与本地 OCR

v0.5.0 已发布到 npm 和 GitHub Release；源码、完整 CI 和四个平台独立安装器已通过工程验证。下面是软件机制验证，不是科研结果或真实模型能力评测。

- 本机 Python **194 项通过**；Node/TypeScript **89 项通过、无跳过**。类型检查、Ruff/格式、版本同步、`uv lock --check --offline` 和 diff 检查通过。
- [完整 CI](https://github.com/zhengye123188/research-cli/actions/runs/37019947263) 在 macOS/Linux × Python 3.10/3.12 四组环境全部通过，源码提交为 `f07592d10c01f8827d4e97aa8316359654e8b262`。每组 Python **191 项通过、3 项 ripgrep 可选测试跳过**；macOS 每组 Node **89 项通过、无跳过**，Linux 每组 Node **88 项通过、1 项 macOS 专属测试跳过**。四组均显式安装固定 OCR 语言数据并实际执行原生 OCR 测试，还完成 npm tarball、Python wheel 实装及模拟任务检查。构建文件哈希的分块读取兼容 Python 3.10。
- 真实 Pi CLI 的默认联网集合为 **66 个工具**：53 科研 MCP、3 文件、6 原生包和 4 协作工具。六类角色按允许工具分工，主 Agent 可动态并行委派，追问保留同一子 Agent 历史。自定义端点认证、保护文件、共享后端无 owner 锁冲突、数值用量只计一次均通过模拟 HTTP 测试。
- 人工 `/agents cancel` 可在主 Agent 等待时结束子 Agent，迟到响应不进入历史；取消后的历史可追问。主/子 Agent 共用模型步数、时间、token 预算；新会话隔离、优雅关闭及超时通过测试。子 Agent 不修改代码/记忆、不执行实验、不嵌套委派，历史仅保留在本进程。
- 复用 `pi-subagents 0.74.0` 的固定内部前台执行器，版本及执行器 SHA-256 检查通过；受控工厂测试确认无环境扩展、skills、项目指令、会话或产物写入。使用同步 Jiti 转换确保虚拟策略模块不会被原生 ESM 导入绕过。完整上游扩展、工作流和后台 fleet 未启用。
- 原生 LiteParse/Tesseract 在真实纯图片 PDF 中识别英文 `RESEARCH SCAN`；真实中文扫描件经离线 Python 导入识别到“科研”“证据与实验验证”等，存在空格及行顺序误差。OCR 缺失/损坏模型拒绝、严格参数、20 页限制、完整私有语言快照、取消、超时和清理检查通过；不保证中文布局、公式或引文准确性。
- 三种官方 `tessdata_fast` 语言模型和 Apache-2.0 许可实际下载后大小/SHA-256 匹配。下载测试包含损坏、重定向、软链接/硬链接、目录变化、挂起请求/流、取消和压缩传输长度；解析阶段不会隐式下载语言模型。
- 最终 npm v0.5.0 tarball 在独立临时目录实装，`setup`、`doctor`、四个内置包、真实 Pi 扩展加载和原生 PDF 导入通过，CLI 与后端版本一致。没有修改用户全局安装。
- [npm v0.5.0](https://www.npmjs.com/package/@lelouch_021015/research-cli/v/0.5.0) 已公开，2026-10-02 核对注册表 `latest` 为 **0.5.0**。公开 tarball 为 **205,293 字节**，与已实装验证的最终包逐字节相同；注册表 SHA-512 为 `sha512-toWn6Ey8cBUSp3IMbct9/NnukpsspBU/jLHBBRU1bYbVA205L/fUcqBn7NYrkW2Ic2t9pz3FqXqVNFfHo80FnQ==`，下载文件也匹配；SHA-256 为 `ef0062818155a331b9413d977e833ff1bc6dd009ca606da13b41313c6d526a18`。本次没有发布 PyPI。
- [四平台构建与安装检查](https://github.com/zhengye123188/research-cli/actions/runs/37019987067) 在 macOS ARM64/x64、Linux ARM64/x64 全部通过，源码同为 `f07592d10c01f8827d4e97aa8316359654e8b262`。每个平台验证内置三种 OCR 模型和许可、原生扫描 PDF OCR、真实 Pi 子 Agent 调用、隔离外部运行环境、中文/空格路径、隐藏持久配置、终端工作区、重装和损坏拒绝。构建采用 `publish=false`，检查通过后另行上传发布。
- [GitHub Release v0.5.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.5.0) 已公开并设为 latest，`v0.5.0` 标签精确指向 `f07592d10c01f8827d4e97aa8316359654e8b262`，不是草稿或预发布。九个公开资产的上传状态、大小和 GitHub SHA-256 均与已校验的本地文件一致，包含四个安装器、四个校验文件和 `install.sh`。
- 公开 `latest/download/install.sh` 返回 HTTP 200，**2,744 字节**，与审查源码和发布资产逐字节相同；SHA-256 为 `1469107f41eae5efebb11e9ae6fedd3ce0936fc522b584907fd84d49cbe20b78`，`sh -n` 通过。四个平台 `.run` 的公开下载终点 HEAD 均为 HTTP 200，`Content-Length` 与已验证文件一致：darwin-arm64 **188,076,967**、darwin-x64 **190,856,182**、linux-arm64 **201,016,035**、linux-x64 **223,534,847** 字节。该轮没有从公开入口重复下载并实装大包；实装证据来自上述四平台 CI，公开资产 SHA-256 确认其内容相同。

## v0.4.0：Pi 包复用与独立分发

- Python **185 项通过**；Node/TypeScript **56 项通过**。类型检查、Ruff/格式、版本同步和 `uv lock --check --offline` 通过。
- 真实 Pi CLI 默认联网请求中确认 **62 个工具**：53 个科研 MCP、3 个文件工具、6 个原生包工具。取消、权限、工具白名单、离线选择和核心初始化失败检查通过。
- 真实 Context7 factory 在 CLI 中完成库标识解析和文档查询；HTTP 返回由测试 fixture 提供。包适配器还验证预先取消、并发取消信号隔离和服务调用独立审计。网页供应商的在线配额、真实检索质量及界面全部呈现仍未验证。
- `pi-docparser` 原生引擎解析真实双页 PDF，保留空白第一页及第二页文本。导入链检查来源哈希、解析器版本、chunks 页码；错误、页数不全、超限、取消及超时测试通过。
- npm tarball 在独立临时目录实装，`setup` 建立版本匹配的 Python 缓存环境，`doctor`、三个内置包、真实 Pi 扩展及安装后 PDF 导入通过。已修复 scoped npm 依赖提升时的包路径解析问题。没有改动用户的全局安装和 API 配置。
- [完整 CI](https://github.com/zhengye123188/research-cli/actions/runs/36966473942) 在 macOS/Linux × Python 3.10/3.12 四组环境通过。每组 Python **182 项通过、3 项 ripgrep 可选测试跳过**，Node **56 项通过**，并完成模拟工具调用、npm tarball 与 Python wheel 实装检查；本机有 ripgrep，这三项也通过。
- [四平台构建与安装检查](https://github.com/zhengye123188/research-cli/actions/runs/36966520191) 全部通过，包含 macOS ARM64/x64、Linux ARM64/x64。隔离外部 Node/Python/uv，验证内置 npm/npx、三个 Pi 包、原生 PDF 导入、Pi/MCP 循环、终端工作区、重装、命令冲突及损坏包拒绝。
- [GitHub Release v0.4.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.4.0) 已公开，标签对应 `34ebdf77973e5dddc65e7303914bff638fedc262`。九个资产的 GitHub SHA-256 与已验证本地文件全部一致，包含四个安装器、四个校验文件和 `install.sh`。安装包内置 Node 22.23.1、Python 3.12.14、Pi 0.99.1、npm/npx 与科研后端。
- v0.4.0 发布时的公开 `latest/download/install.sh` 已逐字节比对审查源码，再实际下载 macOS ARM64 安装器，在临时中文/空格路径安装。`research --version` 为 **0.4.0 (Pi 0.99.1)**，`doctor` 确认后端 0.4.0 与内置 Node 22.23.1，三个 Pi 包可用；没有外部开发运行环境、付费模型调用或现有安装修改。
- [npm v0.4.0](https://www.npmjs.com/package/@lelouch_021015/research-cli/v/0.4.0) 已公开，2026-10-02 该版本发布后核对的注册表 `latest` 当时为 **0.4.0**。注册表 SHA-512 与已验证的 tarball 一致，公开下载文件的 SHA-512 也一致。从注册表下载后，在临时环境再次通过 `setup`、`doctor`、三个 Pi 包、原生 PDF 导入和真实 Pi 扩展加载检查，CLI 与后端均为 0.4.0；没有改动现有全局安装。该次没有发布 PyPI；独立安装包发布不会自动更新 npm 或 PyPI。

依赖审计仍有一项上游 Pi 0.99.1 内部 `brace-expansion` 5.0.9 告警：[上游公告](https://github.com/advisories/GHSA-qhr7-859c-m2p7)。该版本已存在于原锁文件，并由 Pi 的 npm shrinkwrap 锁定；普通 update、override 和非 force 的 `npm audit fix` 未消除它。本次没有强制升级 Pi 或修改上游源码。包的工具许可与宿主代码信任边界见 [安全说明](../SECURITY.md)。

## v0.3.0：工程验证

当前目标是保证 CLI 功能可靠。下面是软件测试与安装验证，不是用户课题结果，也不代表真实模型科研能力。

本地环境：macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1。

- Python：**173 项通过**，包括迁移/归档、论文身份、引文与记忆条件、结构化实验、项目检查、后台 worker 重连/取消及完成状态竞争。
- JavaScript/TypeScript：**25 项通过**；类型检查、Ruff 和格式检查通过。
- 版本检查：npm、Python、两个锁文件及独立安装入口均为 **0.3.0**。
- 12 类合成任务分别使用 memory off/on，**24/24 通过**。两组工具与任务相同，模拟模型执行相同计划；结果只说明工具链和产物核验正常。
- 既有 3 类记忆机制用例完成 off/on 两组测试。该模拟模型刻意回读注入内容，分数差异不代表真实模型质量收益。
- 工具清单与打包内容已核对，默认 53 个科研 MCP 工具加 3 个 Pi 文件工具；新 worker、维护和用量模块包含在 npm/Python 分发文件内。
- npm tarball 在临时目录实际安装，`research setup`、`doctor`、版本核对与真实 Pi 科研扩展加载通过。
- Python wheel / sdist 构建成功；wheel 在隔离工具目录安装，`research-mcp`、`research-legacy` 版本及动态文件读取通过。

[GitHub 完整 CI](https://github.com/zhengye123188/research-cli/actions/runs/36873204826) 在 macOS/Linux × Python 3.10/3.12 四组环境通过。每组 Python 170 项通过、3 项依赖 ripgrep 的可选测试因 runner 未安装该工具而跳过；本机有 ripgrep，这三项也通过。每组 Node 25 项通过，并完成模拟任务与 npm/wheel 安装验证。

远端检查发现并修复了 Linux/Python 3.12 的后台 worker 生命周期问题：启动方式改为不属于原事件循环的独立进程；回归测试在原 CLI 真正退出后认证 worker，再允许实验完成。该修复包含在发布提交 `1313232` 中。

所有上述模型请求使用本机模拟服务和虚构密钥，没有调用付费模型。测试中确实运行了 Pi、MCP、SQLite、临时本地进程和 Unix socket。

公开 LIBSVM CPU 案例是**可选开发示例**，用于演示参数、数据划分、指标和来源记录。它不使用用户科研数据，选参方案没有超过基线，不构成科研能力成绩或完整论文复现。结果与边界见 [示例说明](../evals/public-case.md)。真实科研评估待具体课题开展后设计；Docker/GPU 尚未实机验证。

### v0.3.0 独立安装包与发布状态

[构建与发布工作流](https://github.com/zhengye123188/research-cli/actions/runs/36873884406) 已完成。macOS ARM64、macOS x64、Linux ARM64、Linux x64 四个平台均通过原生构建、临时安装和真实 Pi/MCP 检查；测试隐藏密钥输入、中文/空格路径、内置运行环境、重装和损坏包拒绝。

[GitHub Release v0.3.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.3.0) 已公开，标签对应提交 `1313232b31feea811c27d504a3d61e059bc3a7ee`，资产包含四个安装器、四个 SHA256 文件和 `install.sh`。程序包含 Node 22.23.1、Python 3.12.14、Pi 0.99.1 与后端依赖。macOS 签名、公证和其他 Mac 的 Gatekeeper 下载行为仍未验证。

公开 `latest/download/install.sh` 入口已实际验证：下载脚本逐字节匹配已审查源码，再下载 macOS ARM64 安装包，在临时中文/空格路径安装；CLI 与后端均为 0.3.0，`doctor` 确认使用包内运行环境。没有调用模型，临时安装已清理，用户现有安装和配置未改变。

这次 GitHub 发布没有自动上传 npm 或 PyPI；这些渠道需要另行发布，不能根据 GitHub Release 推断安装到的 npm 版本。

## v0.2.0：历史工程验证

- Python：78 项测试通过，覆盖文献、证据、记忆、MCP、实验、配置保护及下载入口。
- JavaScript / TypeScript：类型检查与 10 项测试通过，其中 5 项启动真实 Pi CLI，覆盖认证、工具调用、权限、压缩、恢复、分支和实验。
- npm tarball：在独立临时目录安装，`research setup` 建立 Python 缓存环境，`doctor` 验证版本，真实 Pi 加载科研扩展。
- Python wheel / sdist：构建与 Twine strict 检查通过；独立工具环境中的 MCP / 兼容 CLI 版本及文件读取验证通过。
- 包文件清单、Ruff 检查与格式检查通过。

集成测试使用真实 Pi、Python stdio MCP、SQLite、本地进程和伪终端，模型由本机 HTTP 服务模拟。模拟请求检查 Bearer 认证头，仅使用虚构密钥，不调用付费 API。

## v0.2.0：历史独立安装包

[v0.2.0 构建与发布](https://github.com/zhengye123188/research-cli/actions/runs/36818786041) 四个平台均通过：

| 平台 | 原生验证环境 | 验证范围 |
|---|---|---|
| darwin-arm64 | macos-15 | 构建、安装、Pi/MCP、终端界面 |
| darwin-x64 | macos-15-intel | 构建、安装、Pi/MCP、终端界面 |
| linux-x64 | ubuntu-24.04 | 构建、安装、Pi/MCP、终端界面 |
| linux-arm64 | ubuntu-24.04-arm | 构建、安装、Pi/MCP、终端界面 |

测试隔离外部 Node / Python / uv，验证中文与空格路径、运行环境导入、隐藏输入密钥、配置权限、当前目录作为工作区、文件读取、MCP 状态、退出清理、重装保留数据、命令冲突及损坏包拒绝。

安装包包含 Node 22.23.1 与 Python 3.12.14。Intel Mac 的 cryptography 使用固定 OpenSSL 静态编译，并检查第三方动态库依赖。macOS 包尚未进行 Developer ID 签名、公证或另一台 Mac 浏览器下载后的 Gatekeeper 验证。

从公开下载入口实际下载 macOS ARM64 安装包，确认入口脚本与已审查源码一致，再在临时中文/空格路径实装；程序和后端版本均为 0.2.0，临时安装已清理。

## v0.2.0：历史发布状态

- [npm `@lelouch_021015/research-cli`](https://www.npmjs.com/package/@lelouch_021015/research-cli) 已公开发布 0.2.0，2026-10-01 从官方注册表核对。
- [GitHub Release v0.2.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.2.0) 已公开，包含四组安装器/校验文件和自动选择平台的 `install.sh`。
- PyPI `research-terminal` 暂未发布，当日只读查询返回 404。发布 GitHub 安装包不会触发 npm / PyPI 上传。

后续代码验证以对应提交的 [CI 结果](https://github.com/zhengye123188/research-cli/actions/workflows/ci.yml) 为准。

## v0.2.0：历史评测边界

`npm run eval:memory` 验证检索、注入与压缩机制，默认模型刻意回读注入记录；不能将开关组分数差异解释为优于原版 Pi。原始输出由脚本生成，保存在被 Git 忽略的 `evals/results/`，复跑方法见 [评测说明](../evals/README.md)。

没有真实大模型、embedding 或 Jev 的质量/费用对照，也没有 Docker 实机验证或公开论文复现。小型合成检索样例仅验证实验执行及指标计算，不证明检索方法提升。

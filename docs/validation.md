# v0.2 验证记录

日期：2026-09-30；独立安装器与云端验证更新于 2026-10-01。开发环境：macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；锁文件为 package-lock.json / uv.lock。

## 实际运行结果

- Python：78 项通过，覆盖原型、来源、引用、记忆修订、MCP stdio、并发实验去重、退出时取消进程与释放工作区锁、保存的 API 凭据访问保护，以及公开下载入口的平台选择、校验拒绝执行和失败清理。
- JavaScript / TypeScript：类型检查通过；10 项测试通过，其中 5 项启动真实 Pi CLI。覆盖 HTTP 认证头、MCP 工具调用、引文保存、项目记忆、压缩、退出恢复、分支、实验取消/去重、步数预算、权限批准与拒绝、配置持久化和凭据访问保护。
- 实际 Pi TUI：伪终端启动成功，执行 /research-status 显示项目统计，Ctrl-D 正常退出，退出码 0。
- npm tarball：在源码目录之外的临时 prefix 安装，research setup 成功建立独立 Python 缓存环境，doctor 确认版本一致；安装后的真实 Pi 能加载科研扩展命令。
- Python wheel / sdist：构建成功，Twine strict 元数据与 README 检查通过；独立 uv tool 环境安装 wheel[mcp] 后，research-mcp / research-legacy 版本检查及实际文件工具调用通过。
- 发布包文件清单检查：npm 不含 node_modules、Python 字节码、研究数据或秘密配置；Python 构建产物也按清单检查。
- ruff 检查和格式检查通过。

### 独立安装器验证

macOS ARM64 实际构建并安装 `.run`，内置 Node 22.23.1 和可搬移的 Python 3.12.14。`scripts/smoke_standalone.py` 在临时目录隔离配置，将 PATH 中外部 node/npm/npx/uv/python/python3 替换为立即失败的命令；安装、doctor 和科研工具循环均成功。

验证包括中文与空格安装路径、Python SSL/SQLite/原生模块导入、伪终端隐藏输入密钥、0600 配置权限、新进程自动读取配置、真实 Pi 文件读取和 MCP project_status 调用、交互界面中的 /research-status 与正常退出、重复安装保留配置与研究数据、拒绝覆盖其他程序，以及拒绝损坏安装包。模型由本机 HTTP 服务模拟并验证认证头，不调用真实付费 API。

提交 `2509d00` 的 [Standalone installers 运行记录](https://github.com/zhengye123188/research-cli/actions/runs/36818786041) 已全部通过，并公开发布四个平台的 `.run` 与 `.sha256`：

| 安装包平台 | 原生验证环境 | 结果 |
|---|---|---|
| darwin-arm64 | macos-15 | 构建、实装、Pi/MCP、TUI 均通过 |
| darwin-x64 | macos-15-intel | 构建、实装、Pi/MCP、TUI 均通过 |
| linux-x64 | ubuntu-24.04 | 构建、实装、Pi/MCP、TUI 均通过 |
| linux-arm64 | ubuntu-24.04-arm | 构建、实装、Pi/MCP、TUI 均通过 |

Intel Mac 在构建机编译锁定的 cryptography，静态链接 OpenSSL 4.0.2，并检查原生模块没有引用构建机的第三方动态库；用户无需安装编译工具。未进行 macOS Developer ID 签名、公证或另一台 Mac 从浏览器下载后的 Gatekeeper 验证。

2026-10-01 另行验证“在项目目录打开终端直接运行”：已将独立包安装到用户目录，全局 `research` 在临时中文项目目录启动，不传 `--workspace`；`/research-status` 返回当前项目，正常退出，数据库位于该项目 `.research/state.sqlite3`。安装包测试也改为从项目 cwd 直接启动 RPC 与 TUI，文件读取、MCP 项目状态和落盘检查均通过。

测试中的模型由本机 HTTP 服务模拟；Pi、MCP、SQLite、本地进程和终端真实运行。没有调用真实付费模型、embedding 或 Jev，也没有 Docker 实机验证。Docker 当前是启动参数与策略测试。

### 自定义端点认证修复

用户实测发现自定义端点返回 401，服务端显示密钥尾部为 `_KEY`。原先传给 Pi 的 `apiKey: "OPENAI_API_KEY"` 被解释为字面值，现改为 Pi 支持的显式环境变量引用 `$OPENAI_API_KEY`。之前的模拟服务未检查 Authorization，导致集成测试遗漏此问题。

新增回归测试在修复前实际复现了失败，修复后通过；所有本机模拟请求现在均验证 Bearer 认证头，包括压缩请求。测试只使用虚构密钥，不保存或输出请求头，并验证密钥不会进入模型消息或 CLI 事件。类型检查、7 项测试和 3 组 memory off/on 机制评测已重新通过；真实 DeepSeek 密钥是否有效仍需用户重启后验证。

## 记忆机制评测

`evals/results/memory-mechanism.json` 保存 3 个合成案例 × memory off/on 的原始结果。模拟模型被编写为回读注入的项目记忆；结果只证明检索、注入和压缩机制能贯通，**不能据此宣称优于原版 Pi 或形成科研质量提升**。

真实模型对照入口已实现：`npm run eval:memory -- --live`。需要本机配置 API key、兼容端点和模型，再运行多次并人工审查。当前没有真实模型成绩。

## 发布与远端状态

提交 `2509d00` 的 [常规 CI](https://github.com/zhengye123188/research-cli/actions/runs/36818769903) 四组 macOS/Linux × Python 3.10/3.12 检查均通过。[v0.2.0 GitHub Release](https://github.com/zhengye123188/research-cli/releases/tag/v0.2.0) 于 2026-10-01 公开，包含四组安装器/校验文件和 `install.sh` 下载入口，无需登录 GitHub。

另外从公开 `releases/latest/download/install.sh` 地址实际下载，确认脚本与已审查源码字节一致，再通过该脚本下载 macOS ARM64 安装包并在临时中文/空格路径实装。`research doctor` 确认程序及后端均为 0.2.0；临时安装已清理，现有用户安装和 API 配置未修改。

npm / PyPI 未上传；当天只读查询两个包的注册表地址均返回 404，不保证名字被预留。GitHub Release 不会自动上传到这两个注册表。后续提交以 [GitHub Actions](https://github.com/zhengye123188/research-cli/actions/workflows/ci.yml) 中对应结果为准。

## v0.1 历史数据

此前 Crossref 元数据、GitHub README/commit、arXiv PDF 接口做过只读实网检查。v0.2 新增的 arXiv 搜索和 GitHub 候选搜索有请求/解析 fixture 测试，尚未作为真实科研检索评测。旧合成检索实验见 `evals/results/retrieval-smoke.json`：8 条测试查询中 overlap/BM25 都满分，说明样例过易，不证明方法提升。

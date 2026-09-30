# v0.2 本地验证记录

日期：2026-09-30。环境：macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；锁文件为 package-lock.json / uv.lock。

## 实际运行结果

- Python：68 项通过，覆盖原型、来源、引用、记忆修订、MCP stdio、并发实验去重、退出时取消进程与释放工作区锁，以及保存的 API 凭据访问保护。
- JavaScript / TypeScript：类型检查通过；10 项测试通过，其中 5 项启动真实 Pi CLI。覆盖 HTTP 认证头、MCP 工具调用、引文保存、项目记忆、压缩、退出恢复、分支、实验取消/去重、步数预算、权限批准与拒绝、配置持久化和凭据访问保护。
- 实际 Pi TUI：伪终端启动成功，执行 /research-status 显示项目统计，Ctrl-D 正常退出，退出码 0。
- npm tarball：在源码目录之外的临时 prefix 安装，research setup 成功建立独立 Python 缓存环境，doctor 确认版本一致；安装后的真实 Pi 能加载科研扩展命令。
- Python wheel / sdist：构建成功，Twine strict 元数据与 README 检查通过；独立 uv tool 环境安装 wheel[mcp] 后，research-mcp / research-legacy 版本检查及实际文件工具调用通过。
- 发布包文件清单检查：npm 不含 node_modules、Python 字节码、研究数据或秘密配置；Python 构建产物也按清单检查。
- ruff 检查和格式检查通过。

### 独立安装器验证

macOS ARM64 实际构建并安装 `.run`，内置 Node 22.23.1 和可搬移的 Python 3.12.14。`scripts/smoke_standalone.py` 在临时目录隔离配置，将 PATH 中外部 node/npm/npx/uv/python/python3 替换为立即失败的命令；安装、doctor 和科研工具循环均成功。

验证包括中文与空格安装路径、Python SSL/SQLite/原生模块导入、伪终端隐藏输入密钥、0600 配置权限、新进程自动读取配置、真实 Pi 文件读取和 MCP project_status 调用、交互界面中的 /research-status 与正常退出、重复安装保留配置与研究数据、拒绝覆盖其他程序，以及拒绝损坏安装包。模型由本机 HTTP 服务模拟并验证认证头，不调用真实付费 API。

另外三个平台由 `Standalone installers` 工作流原生构建和执行同一测试，结果以对应 Actions 运行记录为准。没有进行 macOS 签名、公证或其他 Mac 实机下载验证。

测试中的模型由本机 HTTP 服务模拟；Pi、MCP、SQLite、本地进程和终端真实运行。没有调用真实付费模型、embedding 或 Jev，也没有 Docker 实机验证。Docker 当前是启动参数与策略测试。

### 自定义端点认证修复

用户实测发现自定义端点返回 401，服务端显示密钥尾部为 `_KEY`。原先传给 Pi 的 `apiKey: "OPENAI_API_KEY"` 被解释为字面值，现改为 Pi 支持的显式环境变量引用 `$OPENAI_API_KEY`。之前的模拟服务未检查 Authorization，导致集成测试遗漏此问题。

新增回归测试在修复前实际复现了失败，修复后通过；所有本机模拟请求现在均验证 Bearer 认证头，包括压缩请求。测试只使用虚构密钥，不保存或输出请求头，并验证密钥不会进入模型消息或 CLI 事件。类型检查、7 项测试和 3 组 memory off/on 机制评测已重新通过；真实 DeepSeek 密钥是否有效仍需用户重启后验证。

## 记忆机制评测

`evals/results/memory-mechanism.json` 保存 3 个合成案例 × memory off/on 的原始结果。模拟模型被编写为回读注入的项目记忆；结果只证明检索、注入和压缩机制能贯通，**不能据此宣称优于原版 Pi 或形成科研质量提升**。

真实模型对照入口已实现：`npm run eval:memory -- --live`。需要本机配置 API key、兼容端点和模型，再运行多次并人工审查。当前没有真实模型成绩。

## 发布与远端状态

本记录覆盖 v0.2 的本地验证；没有创建 GitHub Release、上传 npm 或 PyPI。CI 和 Python 发布工作流已随迁移更新，推送后的云端结果以 [GitHub Actions](https://github.com/zhengye123188/research-cli/actions/workflows/ci.yml) 中对应提交为准。之前 v0.1 的 CI 通过不代替 v0.2 验证。

## v0.1 历史数据

此前 Crossref 元数据、GitHub README/commit、arXiv PDF 接口做过只读实网检查。v0.2 新增的 arXiv 搜索和 GitHub 候选搜索有请求/解析 fixture 测试，尚未作为真实科研检索评测。旧合成检索实验见 `evals/results/retrieval-smoke.json`：8 条测试查询中 overlap/BM25 都满分，说明样例过易，不证明方法提升。

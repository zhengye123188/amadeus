# v0.2 本地验证记录

日期：2026-09-30。环境：macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；锁文件为 package-lock.json / uv.lock。

## 实际运行结果

- Python：67 项通过，覆盖原型、来源、引用、记忆修订、MCP stdio、并发实验去重、退出时取消进程与释放工作区锁。
- TypeScript：类型检查通过；6 项测试通过，其中 4 项启动真实 Pi CLI。覆盖 MCP 工具调用、引文保存、项目记忆、压缩、退出恢复、分支、实验取消/去重、步数预算、权限批准与拒绝。
- 实际 Pi TUI：伪终端启动成功，执行 /research-status 显示项目统计，Ctrl-D 正常退出，退出码 0。
- npm tarball：在源码目录之外的临时 prefix 安装，research setup 成功建立独立 Python 缓存环境，doctor 确认版本一致；安装后的真实 Pi 能加载科研扩展命令。
- Python wheel / sdist：构建成功，Twine strict 元数据与 README 检查通过；独立 uv tool 环境安装 wheel[mcp] 后，research-mcp / research-legacy 版本检查及实际文件工具调用通过。
- 发布包文件清单检查：npm 不含 node_modules、Python 字节码、研究数据或秘密配置；Python 构建产物也按清单检查。
- ruff 检查和格式检查通过。

测试中的模型由本机 HTTP 服务模拟；Pi、MCP、SQLite、本地进程和终端真实运行。没有调用真实付费模型、embedding 或 Jev，也没有 Docker 实机验证。Docker 当前是启动参数与策略测试。

## 记忆机制评测

`evals/results/memory-mechanism.json` 保存 3 个合成案例 × memory off/on 的原始结果。模拟模型被编写为回读注入的项目记忆；结果只证明检索、注入和压缩机制能贯通，**不能据此宣称优于原版 Pi 或形成科研质量提升**。

真实模型对照入口已实现：`npm run eval:memory -- --live`。需要本机配置 API key、兼容端点和模型，再运行多次并人工审查。当前没有真实模型成绩。

## 发布与远端状态

本记录覆盖 v0.2 的本地验证；没有创建 GitHub Release、上传 npm 或 PyPI。CI 和 Python 发布工作流已随迁移更新，推送后的云端结果以 [GitHub Actions](https://github.com/zhengye123188/research-cli/actions/workflows/ci.yml) 中对应提交为准。之前 v0.1 的 CI 通过不代替 v0.2 验证。

## v0.1 历史数据

此前 Crossref 元数据、GitHub README/commit、arXiv PDF 接口做过只读实网检查。v0.2 新增的 arXiv 搜索和 GitHub 候选搜索有请求/解析 fixture 测试，尚未作为真实科研检索评测。旧合成检索实验见 `evals/results/retrieval-smoke.json`：8 条测试查询中 overlap/BM25 都满分，说明样例过易，不证明方法提升。

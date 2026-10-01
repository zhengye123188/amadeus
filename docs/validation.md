# 验证记录

更新日期：2026-10-01。开发环境为 macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；依赖由 `package-lock.json` 和 `uv.lock` 固定。

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

npm 当前公开版本仍为 0.2.0；本次 GitHub 发布没有上传 npm 或 PyPI。

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

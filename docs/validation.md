# v0.2 验证记录

更新日期：2026-10-01。开发环境为 macOS ARM64、Node 22.23.1、Python 3.12.13、Pi 0.99.1；依赖由 `package-lock.json` 和 `uv.lock` 固定。

## 工程验证

- Python：78 项测试通过，覆盖文献、证据、记忆、MCP、实验、配置保护及下载入口。
- JavaScript / TypeScript：类型检查与 10 项测试通过，其中 5 项启动真实 Pi CLI，覆盖认证、工具调用、权限、压缩、恢复、分支和实验。
- npm tarball：在独立临时目录安装，`research setup` 建立 Python 缓存环境，`doctor` 验证版本，真实 Pi 加载科研扩展。
- Python wheel / sdist：构建与 Twine strict 检查通过；独立工具环境中的 MCP / 兼容 CLI 版本及文件读取验证通过。
- 包文件清单、Ruff 检查与格式检查通过。

集成测试使用真实 Pi、Python stdio MCP、SQLite、本地进程和伪终端，模型由本机 HTTP 服务模拟。模拟请求检查 Bearer 认证头，仅使用虚构密钥，不调用付费 API。

## 独立安装包

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

## 发布状态

- [npm `@lelouch_021015/research-cli`](https://www.npmjs.com/package/@lelouch_021015/research-cli) 已公开发布 0.2.0，2026-10-01 从官方注册表核对。
- [GitHub Release v0.2.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.2.0) 已公开，包含四组安装器/校验文件和自动选择平台的 `install.sh`。
- PyPI `research-terminal` 暂未发布，当日只读查询返回 404。发布 GitHub 安装包不会触发 npm / PyPI 上传。

后续代码验证以对应提交的 [CI 结果](https://github.com/zhengye123188/research-cli/actions/workflows/ci.yml) 为准。

## 评测边界

`npm run eval:memory` 验证检索、注入与压缩机制，默认模型刻意回读注入记录；不能将开关组分数差异解释为优于原版 Pi。原始输出由脚本生成，保存在被 Git 忽略的 `evals/results/`，复跑方法见 [评测说明](../evals/README.md)。

没有真实大模型、embedding 或 Jev 的质量/费用对照，也没有 Docker 实机验证或公开论文复现。小型合成检索样例仅验证实验执行及指标计算，不证明检索方法提升。

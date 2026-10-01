# Python 兼容 CLI

当前交互式主入口为 Pi 驱动的 `research`，安装和使用见 [README](../README.md)。Python 原型保留为 `research-legacy`，供既有命令及工程测试使用，不应与主入口混用。

从源码运行：

```bash
uv sync --frozen --all-extras
uv run research-legacy --demo
uv run research-legacy --help
```

`--demo` 是确定性工具演示，无需模型密钥，不包含模型推理。非交互文件读取示例：

```bash
uv run research-legacy --demo exec '读取 @README.md' --json
```

模型模式使用本机的 `OPENAI_API_KEY` 和可用模型配置；兼容 Chat Completions 的端点可显式选择协议：

```bash
uv run research-legacy --api chat --model '你的可用模型 ID'
```

Python 包同时提供 `research-mcp` 独立工具服务，Pi 主入口使用科研后端而非该原型的模型循环。PyPI 发布状态与包的区别见 [发布指南](pypi.md)。

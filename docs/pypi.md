# npm CLI 与 PyPI 后端发布

当前两个包版本均为 0.2.0，尚未发布到 npm/PyPI；当前 GitHub 远端是否包含 v0.2 以已推送的提交为准。

| 包 | 安装后命令 | 用途 |
|---|---|---|
| npm `@zhengye123188/research-cli` | `research` | Pi 交互终端、科研扩展、环境安装器 |
| PyPI `research-terminal[mcp]` | `research-mcp`、`research-legacy` | 独立 MCP 服务、历史 Python 原型 |

npm 包携带本项目 Python 后端源码及 uv.lock。`research setup` 用 uv 安装到独立缓存环境，不要求后端已发布到 PyPI。Pi 作为 npm 依赖安装，不复制进源码仓库。

## 本地构建与安装验证

```bash
npm ci
uv sync --frozen --all-extras
npm run check
npm test
uv run pytest -q
uv build --no-sources
uv run python scripts/smoke_install.py dist/research_terminal-0.2.0-py3-none-any.whl
npm pack
```

安装生成的 npm tarball 后运行 `research setup` 和 `research doctor`。可以用 `npm install --prefix /tmp/research-install <tarball>` 验证而不修改用户的全局命令。Python wheel 只安装服务端与原型命令，不能替代 npm 终端包。

## PyPI Trusted Publishing

GitHub 登录不等于 PyPI 授权。使用自己的 PyPI 账号，在 [Publishing 设置](https://pypi.org/manage/account/publishing/) 添加 pending publisher：

| 字段 | 值 |
|---|---|
| Project Name | research-terminal |
| Owner | zhengye123188 |
| Repository | research-cli |
| Workflow | publish.yml |
| Environment | pypi |

2026-09-30 曾查询到该项目 JSON API 为 404，但不保证名字被预留或可注册。若名字冲突，需要同时调整元数据和发布配置。

`.github/workflows/publish.yml` 的 workflow_dispatch 默认 `publish=false`，只检查、构建并保存产物。真正上传要求：
1. 三处版本一致：package.json、pyproject.toml、src/research_cli/__init__.py。
2. 所有变更已推送，CI 通过；PyPI publisher 已配置。
3. 发布同版本 GitHub Release，或在 `v0.2.0` 标签上手动运行并设 `publish=true`。

GitHub Release 会触发真实 Python 包上传；不要用它做演练。不能覆盖已有 PyPI 版本。发布后才可使用：

```bash
uv tool install 'research-terminal[mcp]==0.2.0'
research-mcp --version
```

## npm 发布

先确认 scope 归属和 npm 账号权限。检查 `npm pack --dry-run` 的文件列表，确认没有本地数据和密钥。通过 npm 登录或按 npm 官方要求配置 Trusted Publishing 后，才执行 `npm publish --access public`。该命令会公开发布，不是本地测试。

发布完成后，用户才可以：

```bash
npm install -g @zhengye123188/research-cli
research setup
research
```

当前没有自动触发 npm 上传的工作流；Python 发布工作流不发布 npm。更新发布状态时应附真实包页、版本及 CI 链接。

参考：[uv 工具](https://docs.astral.sh/uv/guides/tools/)、[PyPI pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)、[Pi packages](https://pi.dev/docs/latest/packages)。

# npm CLI 与 PyPI 后端发布

交互式主 CLI 发布到 npm，Python 科研后端可以单独发布到 PyPI。项目自 v0.6.2 更名为 **Amadeus**，新 npm 包名为 `@lelouch_021015/amadeus`，启动命令仍为 `research`。[npm v0.6.2](https://www.npmjs.com/package/@lelouch_021015/amadeus/v/0.6.2) 与[四平台 GitHub Release v0.6.2](https://github.com/zhengye123188/amadeus/releases/tag/v0.6.2) 均已公开并设为 latest，实装测试及公开下载校验通过；范围见[验证记录](validation.md)与[v0.6.2 版本说明](releases/v0.6.2.md)。各渠道需要分别发布；GitHub 推送或独立安装包发布不会更新 npm。PyPI 后端尚未发布，本次也不上传 PyPI。

| 发布渠道 | 包名 | 安装后命令 | 用途 |
|---|---|---|---|
| npm | `@lelouch_021015/amadeus` | `research` | Pi 交互终端、科研扩展、后端环境安装器 |
| PyPI | `research-terminal[mcp]` | `research-mcp`、`research-legacy` | 独立 MCP 服务、历史 Python CLI |

npm 包携带 Python 后端源码及 `uv.lock`，`research setup` 用 uv 安装到独立缓存环境，因此 npm 发布不依赖 PyPI 发布。Pi 作为 npm 依赖安装。

希望用户无需预装 Node、Python 或 uv，可以选择 [GitHub 独立安装器](standalone.md)。它包含 Node 和 Python，运行无需 uv；npm 和 PyPI 安装仍使用用户本机的运行环境。

## 发布 npm 主 CLI

本节展示版本发布步骤。已经公开的同一版本不能重复上传；后续更新先按文末步骤增加版本号。

先注册并登录自己的 [npm 账号](https://www.npmjs.com/signup)。包名中的 `@lelouch_021015` 是 npm scope，登录账号必须拥有该 scope 的发布权限；GitHub 同名账号不自动获得 npm 权限。若使用其他 npm 用户名，先修改 `package.json` 的 `name` 并更新 `package-lock.json`。

在项目根目录执行，Node 版本需要 `>=22.19.0`：

```bash
nvm use 22
npm ci
npm run check
npm test
npm pack --dry-run
npm login --registry=https://registry.npmjs.org
npm whoami --registry=https://registry.npmjs.org
npm publish --access public --registry=https://registry.npmjs.org
```

查看 `npm pack --dry-run` 的文件列表，确认发布内容符合预期。`npm login` 按提示完成浏览器登录，`npm whoami` 显示实际使用的 npm 账号。公开发布 scoped 包需要 `--access public`；直接发布要求 npm 账号开启 2FA，或使用具有相应权限且开启 bypass 2FA 的 granular token。[npm 公开发布说明](https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/)

如果返回 `E403: Two-factor authentication or granular access token with bypass 2fa enabled is required`，本次上传未完成。登录 npm 网站，进入头像菜单 → Account → Two-Factor Authentication → Enable 2FA，按浏览器提示注册安全密钥（Mac 可使用 Touch ID），保存恢复码。随后重新执行 `npm login --registry=https://registry.npmjs.org --auth-type=web`，完成新的认证，再重试发布。此次失败无需增加版本号。不要把密码、恢复码或 token 发到聊天中。[npm 2FA 设置说明](https://docs.npmjs.com/configuring-two-factor-authentication/)

发布后检查注册表：

```bash
npm view @lelouch_021015/amadeus@0.6.2 version --registry=https://registry.npmjs.org
```

用户安装时，需要 Node `>=22.19.0` 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
npm install -g @lelouch_021015/amadeus
research setup
research configure
cd "/你的项目目录"
research
```

`research configure` 交互填写模型 API 信息。启动时所在目录就是工作区，科研数据保存在该项目的 `.research/`。当前没有自动上传 npm 的 GitHub 工作流。

## 通过 GitHub Actions 发布 PyPI 后端

推荐使用现有 `publish.yml` 工作流和 PyPI Trusted Publishing。GitHub 登录与 PyPI 登录分别配置；Trusted Publishing 使用 OIDC，不需要将长期 PyPI API token 保存到仓库。[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)

新包先用自己的 PyPI 账号打开 [Publishing 设置](https://pypi.org/manage/account/publishing/)，添加 pending publisher：

| 字段 | 值 |
|---|---|
| Project Name | `research-terminal` |
| Owner | `zhengye123188` |
| Repository | `amadeus` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

若包已属于自己的 PyPI 账号，在该项目的 Publishing 设置中添加 publisher。Pending publisher 不会预留包名；名字被占用时，需要调整项目元数据和发布配置。[PyPI 新项目发布说明](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

将最终提交推送到 GitHub，并确认 CI 通过。工作流只由 `workflow_dispatch` 手动触发，发布 GitHub Release 不会自动上传到 PyPI。先运行默认的 `publish=false` 验证构建：

```bash
gh workflow run publish.yml --ref main -f publish=false
```

真正发布要求 `package.json`、`pyproject.toml`、`src/research_cli/__init__.py` 版本一致，而且工作流运行在完全匹配的 `vVERSION` 标签上。先同步远端标签：

```bash
git fetch origin --tags
```

如果对应版本已经发布独立安装器，复用该发布的标签，不要移动或重新创建。否则，为已经通过 CI 的提交创建并推送完全匹配的标签。在 GitHub **Actions → PyPI release → Run workflow** 中选择该标签，再勾选 `publish`。以 0.6.2 为例，只有 `v0.6.2` 标签存在且指向通过验证的源码、并且另行决定发布 PyPI 后端时运行：

```bash
gh workflow run publish.yml --ref v0.6.2 -f publish=true
```

`publish=true` 会真实上传。只有工作流上传成功并能从 PyPI 查询到版本后，才向用户提供安装命令：

```bash
uv tool install 'research-terminal[mcp]==0.6.2'
research-mcp --version
```

这会安装 MCP 服务和 Python CLI；Pi 交互式 `research` 命令来自 npm 包或独立安装器。

## 在本地发布 PyPI 后端

也可以使用 PyPI API token 手动上传。先在项目根目录完成验证，确保 `dist/python/` 只有此次要发布的 wheel 和源码包：

```bash
uv sync --frozen --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build --no-sources --out-dir dist/python
uvx --from 'twine>=6,<7' twine check --strict dist/python/*
uv run python scripts/smoke_install.py dist/python/research_terminal-0.6.2-py3-none-any.whl
uvx --from 'twine>=6,<7' twine upload dist/python/*
```

上传提示时，用户名填 `__token__`，密码填自己的 PyPI API token。不要把 token 写进源码、命令示例或 GitHub。这里单独使用 `dist/python/`，避免把 npm tarball 或独立安装器混入上传文件。[Python 包发布指南](https://packaging.python.org/en/latest/tutorials/packaging-projects/)

## 后续版本更新

使用统一脚本更新版本，避免前端、后端和安装入口不一致。下面的 0.6.3 只是后续补丁版本示例：

```bash
npm run version:set -- 0.6.3
npm run version:check
```

脚本同步 `package.json`、`package-lock.json`、`pyproject.toml`、Python 版本常量、`uv.lock` 和 `packaging/download.sh`，不改变依赖版本。补充 CHANGELOG 和对应发布说明，完成检查、构建与安装验证，再提交到 GitHub并分别发布需要更新的渠道。

npm 和 PyPI 已发布的同名同版本文件不能直接覆盖。修复后发布新版本；更新发布状态时附上实际包页面和成功的工作流链接。

# npm CLI 与 PyPI 后端发布

交互式主 CLI 发布到 npm；Python 科研后端发布到 PyPI。当前源代码版本均为 `0.2.0`，是否已在注册表发布，请用下文的查询命令确认。

| 发布渠道 | 包名 | 安装后命令 | 用途 |
|---|---|---|---|
| npm | `@zhengye123188/research-cli` | `research` | Pi 交互终端、科研扩展、后端环境安装器 |
| PyPI | `research-terminal[mcp]` | `research-mcp`、`research-legacy` | 独立 MCP 服务、历史 Python CLI |

npm 包携带 Python 后端源码及 `uv.lock`，`research setup` 用 uv 安装到独立缓存环境，因此 npm 发布不依赖 PyPI 发布。Pi 作为 npm 依赖安装。

希望用户无需预装 Node、Python 或 uv，可以选择 [GitHub 独立安装器](standalone.md)。它包含这些运行环境；npm 和 PyPI 安装仍使用用户本机的运行环境。

## 发布 npm 主 CLI

先注册并登录自己的 [npm 账号](https://www.npmjs.com/signup)。包名中的 `@zhengye123188` 是 npm scope，登录账号必须拥有该 scope 的发布权限；GitHub 同名账号不自动获得 npm 权限。若使用其他 npm 用户名，先修改 `package.json` 的 `name` 并更新 `package-lock.json`。

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

查看 `npm pack --dry-run` 的文件列表，确认发布内容符合预期。`npm login` 按提示完成浏览器登录，`npm whoami` 显示实际使用的 npm 账号。公开发布 scoped 包需要 `--access public`；首次手动发布建议在 npm 账号开启 2FA，并按发布提示完成验证。官方文档也支持具有相应权限和 2FA bypass 的 granular token。[npm 公开发布说明](https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/)

发布后检查注册表：

```bash
npm view @zhengye123188/research-cli@0.2.0 version --registry=https://registry.npmjs.org
```

用户安装时，需要 Node `>=22.19.0` 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
npm install -g @zhengye123188/research-cli
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
| Repository | `research-cli` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

若包已属于自己的 PyPI 账号，在该项目的 Publishing 设置中添加 publisher。Pending publisher 不会预留包名；名字被占用时，需要调整项目元数据和发布配置。[PyPI 新项目发布说明](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

将最终提交推送到 GitHub，并确认 CI 通过。工作流只由 `workflow_dispatch` 手动触发，发布 GitHub Release 不会自动上传到 PyPI。先运行默认的 `publish=false` 验证构建：

```bash
gh workflow run publish.yml --ref main -f publish=false
```

真正发布要求 `package.json`、`pyproject.toml`、`src/research_cli/__init__.py` 版本一致，而且工作流运行在完全匹配的 `vVERSION` 标签上。以 `0.2.0` 为例，若标签尚不存在：

```bash
git tag v0.2.0
git push origin v0.2.0
```

标签已经存在时复用该标签，不要重复创建。标签应指向包含当前发布工作流和该版本代码的提交。然后在 GitHub **Actions → PyPI release → Run workflow** 中选择 `v0.2.0` 并勾选 `publish`，或执行：

```bash
gh workflow run publish.yml --ref v0.2.0 -f publish=true
```

`publish=true` 会真实上传。只有工作流上传成功并能从 PyPI 查询到版本后，才向用户提供安装命令：

```bash
uv tool install 'research-terminal[mcp]==0.2.0'
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
uv run python scripts/smoke_install.py dist/python/research_terminal-0.2.0-py3-none-any.whl
uvx --from 'twine>=6,<7' twine upload dist/python/*
```

上传提示时，用户名填 `__token__`，密码填自己的 PyPI API token。不要把 token 写进源码、命令示例或 GitHub。这里单独使用 `dist/python/`，避免把 npm tarball 或独立安装器混入上传文件。[Python 包发布指南](https://packaging.python.org/en/latest/tutorials/packaging-projects/)

## 后续版本更新

下一版本需同步 `package.json`、`pyproject.toml`、`src/research_cli/__init__.py`，并更新 `package-lock.json` 和 `uv.lock`。`npm version 0.2.1 --no-git-tag-version` 可以更新 npm 版本及锁文件；修改 Python 版本后运行 `uv lock`，重新检查、构建并发布对应的 `v0.2.1`。

npm 和 PyPI 已发布的同名同版本文件不能直接覆盖。修复后发布新版本；更新发布状态时附上实际包页面和成功的工作流链接。

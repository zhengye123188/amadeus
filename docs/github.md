# 上传到你的 GitHub

以下是从本地项目发布到自己 GitHub 的步骤，适用于尚未关联远程仓库的副本。若从 GitHub 克隆本仓库，请直接使用已有远程或 Fork，不要再次创建同名仓库。默认创建公开仓库；暂不公开时把 `--public` 改成 `--private`。

## 最短路径：GitHub CLI

安装 GitHub CLI `gh` 后，先登录你的 GitHub 账号：

```bash
gh auth login
```

按照提示选择 GitHub.com、HTTPS、浏览器登录。在浏览器完成授权，不要把 token 发到聊天或写进项目文件。

进入本项目目录并验证：

```bash
cd /path/to/research-cli
uv sync --frozen --all-extras
uv run pytest -q
git status --short
```

提交并创建仓库：

```bash
git add .
git diff --cached --stat
git commit -m "Initial release of ResearchCLI"
git branch -M main
gh repo create research-cli --public --source=. --remote=origin --push
gh repo view --web
```

`research-cli` 是仓库名，可自行更换；省略 owner 时默认使用当前登录账号。若名字已存在，请选新名字，或按下节连接已有空仓库。

`.gitignore` 排除了虚拟环境、API key 配置、会话、输入历史和本地实验日志；提交前仍应检查暂存文件没有私人资料。不要使用 `git add -f` 强制加入这些文件。

如果 `git commit` 提示身份未配置，在本仓库设置你自己的名字和 GitHub 提交邮箱后重试：

```bash
git config user.name '你的名字'
git config user.email '你的 GitHub 提交邮箱'
```

## 已经在网页创建了空仓库

先完成上面的 `git add`、`git commit` 和分支改名，再执行：

```bash
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

网页建仓库时不要勾选生成 README、LICENSE 或 .gitignore，本项目已经提供这些文件。若远程已有内容，先检查两边差异并合并，不要强推覆盖。若提示 origin 已存在，先用 `git remote -v` 检查，不要反复添加。

## 后续更新

```bash
git add .
git commit -m "Describe the change"
git push
```

在 GitHub 的 Actions 页面查看测试结果。CI 配置的存在不代表云端已经通过；首次推送后才会真正运行。仓库描述可写：

> Interactive research CLI agent with dynamic tool calling, evidence tracking, MCP, retrieval and controlled experiments.

README 如实区分已实现能力、mock 测试、真实接口验证和未完成的模型评测。发布代码不等于发布 PyPI 包或完成论文复现。

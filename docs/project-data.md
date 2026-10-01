# 项目数据与升级

研究记录保存在工作区 `.research/state.sqlite3`；证据产物和实验快照分别位于 `artifacts/` 与 `jobs/`。数据库 schema 独立于 CLI 版本。v0.2 数据库首次打开时迁移为 schema 1，保留记录 ID、正文、时间和记忆历史；更高版本 schema 会拒绝打开，避免旧程序改写新数据。

在 CLI 内可请求调用 `backup_project`，或直接运行后端维护命令：

```bash
python -m research_cli.maintenance backup --workspace .
python -m research_cli.maintenance info --workspace .
python -m research_cli.maintenance restore /path/to/project.zip --workspace /path/to/new-project
```

备份使用 SQLite backup API，包含已提交的 WAL 数据、证据产物和实验文件，以 SHA256 校验每个文件。默认放在 `.research/backups/`，权限为 0600。运行中的任务需要先完成或取消。默认上限 512 MB，较大数据集应独立保存。

恢复只允许目标工作区没有 `.research`。恢复前验证格式、schema、文件列表、校验和、SQLite 完整性，以及压缩包路径和符号链接。不会覆盖现有研究记录。迁移到新机器后仍需单独准备运行依赖和数据集。

归档包含研究内容及代码快照，分享前应检查内容。用户 API 配置、项目顶层源码和 Pi 对话记录不在此归档内；项目源码继续由 Git 管理，Pi 会话使用 Pi 自身的会话目录。

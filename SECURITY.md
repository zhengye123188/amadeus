# 执行与数据边界

默认 `--permission ask --execution disabled`。Pi 工具事件上的本地策略约束模型发起的文件、科研工具和实验操作。read-only 禁止业务写入，但会话、索引、缓存和审计仍写入本地。workspace-write 自动允许写入；执行需单独审批或显式 --approve-experiments。付费 embedding/Jev 工具仍需审批。

Pi 的 read/write/edit 有 workspace、私有路径、symlink 和 hardlink 检查；递归搜索通过 Python 的受限工具。write 是覆盖写入，Pi edit 使用其原文匹配语义；不要把旧 Python 原型的 SHA 冲突检查当成 Pi 所有文件工具的保证。普通 shell/用户 ! 入口关闭，实验走 run_experiment。

Python 服务端用 Schema 和 Registry 再验证。扩展为已批准的具体工具/参数签发短时、一次性 HMAC，模型不能自行生成批准；令牌不进入 Python 审计。审批策略不是 OS 沙箱，也不对敌对的本地进程、显式加载的扩展或用户自身提供隔离。

所有扩展/MCP 代码具有宿主权限。主启动器不自动加载其他项目扩展、skills、AGENTS.md 或 MCP 配置；显式 --extension 仍是可信代码。模型认证、Pi 设置与会话使用 Pi 自己的目录，可通过 PI_CODING_AGENT_DIR 隔离。不要将该目录放入可被模型读取的普通项目文件夹。

研究数据保存在被 Git 忽略的 .research/；Pi 对话另存其 session 目录。两者都可能含全文、私有代码、用户输入和实验日志。不要上传它们或在公开 issue 粘贴凭据。自定义模型端点会收到发送给模型的材料；工具标记只读并不意味着数据不离开机器。

Docker 仅隔离实验进程：无网络、只读根、有限 CPU/内存/PID、非 root、只挂载快照。没有磁盘配额或 GPU。local 模式拥有当前用户的主机访问能力；环境变量过滤和复制目录不能把它变成沙箱。需要强隔离时隔离整个 Pi/MCP 进程。

MCP 关闭会取消它拥有的实验。意外退出后的状态是 interrupted_unknown，不根据旧 PID 发信号或重放。request_id 用于去重，不能消除所有进程启动/记录保存之间的未知窗口。

PDF 解析使用线程，超时不能强制中止解析线程；不应导入恶意构造的 PDF。科研引用只校验原文子串，不能自动证明语义支持、作者代码身份、科学真实性或复现成功。

问题报告应提供最小复现并去掉秘密和私有材料；如仓库启用 GitHub Private vulnerability reporting，使用该私密渠道。

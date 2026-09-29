# 本地验证记录

日期：2026-09-29。环境：macOS ARM64，Python 3.12.13；依赖锁定于 `uv.lock`。没有配置真实模型/embedding/TypeSafe key；未安装 Docker。

自动化测试：本次 `uv run pytest -q` 对应环境下 **56 项通过**（5.72 秒），ruff 检查及格式校验通过。测试项包含模型流式协议、动态工具循环、权限、文件冲突、证据定位、上下文压缩、取消恢复、本地实验子进程、Docker 启动参数、MCP stdio、embedding/Jev SDK 适配和伪终端交互。SDK 网络调用使用 mock；本地 MCP、进程和终端实际运行。以之后实际运行的输出为最新状态。

只读联网 smoke check 使用临时目录，没有加入用户材料：

| 接口 | 请求 | 实际结果 |
|---|---|---|
| Crossref | retrieval augmented generation，2023–2026，1 条 | 返回一条元数据，DOI `10.1002/9781394374717.ch03`；只验证接口，不评价论文质量 |
| GitHub | `python/cpython` | commit `42e62d6d22458e4759dc06ae36fb7d02a0a741d6`，README 8907 字符；未执行仓库代码 |
| arXiv | PDF `2005.11401` | 19 页、51 个文本块；不代表公式/表格重建正确 |

合成检索实验的真实原始输出见 `evals/results/retrieval-smoke.json`。8 条 test 查询，overlap 和 BM25 的 Recall@3、MRR@10 均为 1.0。这个结果表明样例过易，不能证明 BM25/Jev/hybrid 的质量提升。未调整 test 来制造优势。

构建：`uv build --offline` 已生成 wheel 和 sdist，构建产物在被忽略的 `dist/`。在独立临时虚拟环境安装 wheel 及运行依赖后，`research --demo exec` 成功读取临时文件并返回完整 JSONL 事件，退出码 0；不依赖 editable 安装。两种安装包均检查过，未包含 `.research/`、`.venv/`、`.git/`、`.env` 或本地 `research.toml`。

工程包含 GitHub Actions 配置，但尚未推送，云端 CI 未运行。正式发布前应在目标模型服务和 Docker 环境复验，并公开真实端到端任务的重复结果。

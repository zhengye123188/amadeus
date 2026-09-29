# 可复跑的 CPU 实验

本目录是 MIT 许可的原创合成数据与 Python 标准库实验。没有下载论文内容，没有真实论文复现或模型能力声明。

```bash
uv run python examples/retrieval_lab/run.py --split dev --output /tmp/retrieval-dev.json
uv run python examples/retrieval_lab/run.py --split test --output /tmp/retrieval-test.json
```

对比 token overlap 与 BM25，报告 Recall@3、MRR@10、每条查询排名、数据和代码 SHA256、Python 版本。dev 为 4 条查询，test 为 8 条；按文档 ID 解决同分。请不要根据 test 修改算法。这个很小的公开测试集只能验证实验接口，应另准备有标注的外部数据评估泛化。没有显著性检验，不以单次延迟判断性能，也不保证改进一定有效。

在真实模型的 CLI 中可以直接输入：

> 检查 examples/retrieval_lab 的评价代码和 dev 样例，解释 overlap 的不足。先提出一个可证伪的改进假设，不改测试集。不要运行命令，先告诉我对比方案。

然后启动带 Docker 执行权限的 CLI，在模型提出 `run_experiment` 时审阅完整参数。示例参数如下（模型可自行选择，不是强制工作流）：

```json
{"argv":["python","run.py","--split","test"],"cwd":"examples/retrieval_lab","timeout_seconds":30}
```

实验写入独立快照；用 `job_status` 看结果，`read_job_file` 读取 `metrics.json`。`/jobs` 和 `/cancel JOB_ID` 可由用户直接操作。退出 CLI 会取消仍在运行的实验。固定镜像、源码和数据后，比较实际指标及失败案例；不要把 smoke test 写成“复现论文”。

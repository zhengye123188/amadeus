# 结论审查与项目开发

所有能力是按需工具，用户可从任何研究或开发问题开始。检索、修改、验证与比较没有固定调用顺序。

## 假设状态

`remember_research` / `update_memory` 对 `supported` 或 `refuted` 假设要求显式 `assessment`：

```json
{
  "condition": "固定测试集的 accuracy >= 0.8",
  "rationale": "依据本次生成的评价文件；尚待独立审查",
  "metric_checks": [
    {"job_id": "job_...", "metric": "accuracy", "operator": "gte", "threshold": 0.8}
  ]
}
```

指标检查是合取条件：所有条件成立才允许 `supported`，至少一个不成立才允许 `refuted`。每个实验引用都必须有检查，实验必须完成并产生经校验的有限数值指标；引用时重新检查文件哈希。条件与科学假设之间的合理性仍需独立判断。

仅使用文献时，证据必须包含原文精确引文、与假设一致的 claim，以及对应的 supports/contradicts 关系。关系和理由是模型解释，保存为 `model_reviewed`，不能据此声称已人工确认。没有 assessment 的记录为 `unreviewed`；旧记录保留原始状态，补充未审查标签。用户可用 `/review-memory mem_...` 审查展示的具体修订，明确确认或标记需要修改；后续编辑会重置确认状态。

`observed` 科学结果要求经校验的实验指标。命令报错或测试失败使用 `observation_type: "execution"`，记录执行情况，不据此推断算法优劣。

## 代码导航与回退

- `search_project`：glob、大小写、分页；regex 使用 ripgrep，未安装时可用字面搜索。
- `inspect_symbols`：Python AST 的 import、函数和类位置；不执行源码。
- `create_checkpoint`：修改前保存显式选择的 UTF-8 文件，可包括尚不存在的新文件路径。
- `inspect_checkpoint`：查看差异并取得当前文件哈希。
- `restore_checkpoint`：提供所有当前哈希后恢复；过期检查会拒绝覆盖，最初不存在的文件会被删除。它只覆盖选中的文件，完整项目版本继续用 Git 管理。
- `run_project_check`：在原项目目录测试或构建，可访问已准备的依赖；独立记录运行前源码快照、日志、退出状态和请求 ID。它需要执行授权，可能产生测试或构建文件。

`run_experiment` 继续在独立快照运行科学实验。以上写入、执行操作沿用 CLI 权限控制；私有状态、凭据和越界路径保持受限。

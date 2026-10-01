# 论文比较与复现记录

这些能力是交互式 CLI 中按需调用的工具。可以从任意论文、实验或研究问题开始，随时修改方向；工具不会自动启动一套固定流程。

## 论文身份与版本

Crossref 检索结果会按规范化 DOI 归入 `paper_id`，arXiv 的 v1、v2 等版本保留各自 `source_id`，并归入同一个无版本号论文身份。大小写和 DOI URL 表示差异不会产生新的 DOI 身份。相似标题不会触发合并。

`get_paper_identity` 可以通过 `paper_id`、DOI 或 arXiv ID 查询关联材料，`list_papers` 支持分页。使用 `register_paper_identity` 可以明确登记别名或关联已有材料。向已有 `paper_id` 添加材料时，需要传入当前 `expected_revision`。若两个标识已经属于不同论文，工具会拒绝合并，避免混淆独立记录。

旧版材料尚未有 `paper_id` 时，也会检查其已有 DOI/arXiv 元数据；不能将标识冲突的多篇论文仅凭相同标题归入一个身份。

导入全文时，可以提供检索结果中的 `paper_id`：

```json
{"path":"papers/example.pdf","paper_id":"检索结果中的 paper_id"}
```

下载 arXiv PDF 会自动关联 arXiv 论文身份，并保存请求版本。未指定版本时，记录会明确说明请求的是最新版本，实际解析版本尚未独立确认。全文的文件哈希、文本哈希和页码定位仍会保存；扫描件 OCR、图表与公式重建尚未实现。

已经关联的同一材料不能被重新分配给另一篇论文，重复导入也不会清除原有关联。

## 结构化比较

`save_research_map` 为一篇论文保存以下维度：

| 字段 | 内容 |
| --- | --- |
| `question` | 研究问题与适用范围 |
| `method` | 方法与核心机制 |
| `assumptions` | 方法依赖的假设 |
| `dataset` | 数据集和划分 |
| `evaluation` | 指标、协议与基线 |
| `limitations` | 作者报告的限制或研究者提出的待检验问题 |

每条内容包含 `text`、`basis` 与 `evidence_ids`。`reported` 必须引用本论文全文中实际存在的引文证据；`inference` 与 `unknown` 用于明确记录推断或未知事项。检查引文存在并不能证明解读正确。

```json
{
  "paper_id":"已有论文身份",
  "expected_revision":0,
  "fields":{
    "method":[{"text":"论文使用的具体方法","basis":"reported","evidence_ids":["已有证据 ID"]}],
    "limitations":[{"text":"待验证的改进方向","basis":"inference","evidence_ids":[]}]
  }
}
```

`expected_revision: 0` 创建记录，更新时传入当前版本号。保存会替换整份字段集合，旧版本保留；`read_research_map` 可以查看当前记录和修订历史。

`compare_papers` 并列展示记录、缺失维度，以及数据集或评价描述不一致的提示。工具不会因为两个表格里的分数不同就判定方法优劣，也不会保证描述相同就具备科学可比性。

`export_research_map` 可生成 JSON、Markdown 或 BibTeX 产物。BibTeX 仅导出已经保存的标题、作者、年份和标识等元数据，不补造缺失字段。工具返回内容及可用 `read_artifact` 读取的产物 ID。

## 复现准备与阶段记录

`save_reproduction_plan` 记录固定仓库 commit，以及依赖、数据、配置、硬件、执行命令和论文指标目标。仓库必须来自实际 `inspect_repository` 结果；源码记录来自固定 commit 的 `read_repository_file`，并保存文件内容 SHA256。

主要字段：

- `paper_id`、`repository_source_id`、`commit`：论文及已检索的仓库版本。
- `association_evidence_ids`：论文中明确提到仓库 URL 的引文；仅提到 URL 不代表作者官方代码。
- `code_source_ids`：固定 commit 的源码文件记录；基线验证会比对实际执行快照中的文件哈希。
- `dependencies`、`data`、`configuration`、`hardware`、`command`：由用户或 Agent 整理、待执行验证的准备信息。
- `smoke_command`：可选的最小运行命令；未填写时用基线命令检查 `smoke_passed` 的实验关联。
- `dataset_id`、`split`、`protocol`：应与结构化实验中的数据集和评价条件一致。
- `targets`：指标名称、目标值、绝对容差、优化方向及论文引文证据。

保存结果包含准备信息缺口。准备描述不等于环境实际可用。`read_reproduction_plan` 返回修订历史，`list_reproduction_plans` 支持分页。

`update_reproduction_stage` 可以记录以下阶段，支持直接更新而不强制逐步执行：

| 阶段 | 必要条件与含义 |
| --- | --- |
| `drafted` / `blocked` | 方案草稿或阻塞原因 |
| `environment_ready` | 准备信息齐全；仍是声明性记录 |
| `smoke_passed` | 与声明的最小运行命令对应的实验进程完成；不代表论文结果复现 |
| `baseline_completed` | 完成的结构化实验、可重新校验的数值及产物；命令、数据集、划分、评价协议及所声明源码文件与方案一致 |
| `metrics_matched` | 基线条件成立，全部目标指标在所声明绝对容差内 |

失败、仍在运行、未知中断或没有验证指标产物的任务，无法成为成功基线证据。修改产物、数据或执行快照清单后，重新校验也会拒绝原成功声明。更新方案会回到 `drafted`，避免新的条件继承旧方案的执行结论。

这些检查证明记录与文件、进程及数值之间的对应关系。它们尚不能证明所选源码文件覆盖了全部算法、指标定义等同于论文定义、数据真实可信或科学结论成立。未声明的仓库文件、依赖及硬件仍需要审查；全文引文的语义也需要研究者确认。即使指标匹配，仓库的作者关联状态也不会自动升级。

## 验证

测试使用本地材料与模拟 HTTP 响应，覆盖 DOI/arXiv 身份、版本关联、错误合并拒绝、全文关联、引文归属、乐观修订、比较提示、引用导出及复现阶段限制。一项测试在本地实际运行最小 Python 程序，采集结构化指标，检查方案修改和指标文件篡改无法沿用成功状态。该程序是软件机制测试，尚不构成公开论文复现效果评测。

# 按工具职责分工的协作与本地 OCR

这些能力属于 v0.5.0 源码开发版，尚未更新已发布的 npm 和独立安装器。用 `npm ci`、`uv sync --frozen --all-extras` 安装源码依赖，再运行 `npm start`。

## 动态协作

主 Agent 接收用户问题，选择合适的角色和具体任务，可同时委派一至三项独立工作。角色规定工具范围，没有固定执行顺序，也不要求每次启动所有角色。可以从找论文、读扫描件、分析代码或检查已有实验中的任意问题开始。

| 角色 | 职责 | 工具范围 |
| --- | --- | --- |
| `literature` | 文献检索、研究现状比较 | 论文检索、文献库与身份查询、候选代码关联、网页检索和读取 |
| `documents` | 论文读取与资料导入 | 工作区文件读取、PDF/OCR 导入、arXiv 下载、原文 chunks、来源和证据查询 |
| `code` | 项目和论文代码分析 | 文件读取、代码/符号搜索、Git diff、固定版本仓库读取、Context7 文档 |
| `experiments` | 已有实验分析 | 作业状态、日志、指标/产物、实验比较及复现计划查询 |
| `memory` | 记忆和证据整理 | 约束、假设、记录、原文与证据、研究比较和复现计划查询 |
| `review` | 依据核查与方法审阅 | 原文、证据、论文比较、代码与已有实验结果读取 |

所有角色有项目状态和记忆查询工具。具体列表由 `/agents roles` 展示，并与当前激活的工具取交集；离线模式会移除联网工具。资料导入和联网检索可以保存检索缓存、来源和 chunks；“读取角色”不表示后端完全不写缓存。

子 Agent 不能写代码、修改科研记忆、保存结论、启动/取消实验、运行 shell 或再次委派。这些动作由主 Agent 使用现有审批和验证机制完成。子 Agent 分析仍是待核实意见；引用其他 Agent 的意见不会自动变成证据或人工确认。

示例对话：

```text
让文献 Agent 比较近三年的相关论文，让代码 Agent 分析当前实现，再汇总可验证的改进方向。
让文档 Agent 使用英文和简体中文 OCR 导入 papers/scanned.pdf，并指出可疑的识别内容。
追问刚才的代码 Agent：这个改进需要修改哪些文件？
让实验分析 Agent 比较已保存的基线与候选结果，再让审阅 Agent 检查结论的依据。
```

## 管理与预算

模型可调用 `agent_tasks`、`agent_followup`、`agent_status` 和 `agent_cancel`。用户可以使用：

```text
/agents
/agents roles
/agents cancel agent_任务编号
```

每次最多三项并发任务，每会话最多保留十六个子 Agent。追问使用同一子 Agent 历史及原来的角色，继承此时主 Agent 所选模型。子 Agent 与主 Agent 共享工作区、科研库和一个 MCP 服务，不启动互相竞争的科研后端。

子 Agent 继承主会话实际选择的模型、认证和推理等级，包括自定义 DeepSeek 端点。主 Agent 和所有子 Agent 共用当前提示的模型步数、时间、token 和费用预算；`/usage` 汇总全部已记录响应，账本另存任务 ID、角色和父会话 ID。token/费用是软限制，并发中的请求可能超出额度，价格未知仍为未知。

委派工具在前台等待完成，期间显示任务状态并支持取消。主会话取消、关闭、重新加载会结束子 Agent。这里没有脱离 CLI 持续运行的后台子 Agent，也没有跨进程恢复子 Agent 历史；科研来源、记忆、证据和实验记录仍持久保存在 `.research`。

## 本地 OCR

OCR 复用现有 `pi-docparser 4.0.0` / LiteParse 2.10.1 中的 Tesseract 引擎。无需额外安装 Tesseract 可执行文件、云端 OCR 账号或模型 API。npm/源码首次使用需要显式安装语言数据：

```sh
research ocr install --languages eng,chi_sim
research ocr list
# 繁体中文按需安装
research ocr install --languages chi_tra
```

源码运行可将 `research` 替换为 `npm start --`。安装默认选择英语和简体中文。下载来自官方 `tesseract-ocr/tessdata_fast` 的固定 Git commit，大小和 SHA-256 通过后原子保存。默认目录为 `~/.config/research-cli/tessdata`，支持 `XDG_CONFIG_HOME` 和用户设置的 `RESEARCH_OCR_TESSDATA`。新版独立安装器构建将包含三种语言及 Apache-2.0 许可。

科研工具参数为：

```json
{
  "path": "papers/scanned.pdf",
  "ocr": true,
  "ocr_languages": ["eng", "chi_sim"]
}
```

可用后端配置 `ocr_tessdata_path` 指定本地语言目录；工具参数 `tessdata_path` 只允许工作区内目录。模型缺失或损坏会报错，解析时不会隐式联网下载，不会把文件上传 OCR 服务。OCR 默认关闭，开启后只支持 PDF，每份最多 20 页、20 MB；普通文本型 PDF 仍最多 200 页。

来源记录保留文件哈希、页码、OCR 引擎、语言和语言模型哈希。真实扫描 PDF 测试已验证英文和中文识别，但中文空格、阅读顺序和复杂版式可能偏差。公式、表格及用作引用的文字需要核对原页；OCR 成功不能证明科学结论正确。

## 复用范围

协作复用 [pi-subagents](https://github.com/nicobailon/pi-subagents) 的固定版本 0.74.0 前台执行器。该执行器的可注入子会话工厂位于包内部，因此适配器校验版本与执行器文件哈希，升级必须重新审查。Research CLI 提供角色白名单、受控 Pi 子会话、主工具转发、共享预算和管理命令；不自动加载上游完整扩展、工作流或环境中的 Agent 定义。

OCR 来源与许可见 [第三方说明](../THIRD_PARTY_NOTICES.md)。Pi 官方包目录提供发现入口，包由各自维护者开发；目录收录不等于 Pi 官方保证其兼容性。

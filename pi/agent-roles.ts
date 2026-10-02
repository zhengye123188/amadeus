import { effects } from "./policy.ts";

const research = (...names: string[]) => names.map(name => `mcp__research__${name}`);
const shared = research("project_status", "memory_context", "list_memory", "get_record");
/** Roles are capability allowlists, not a prescribed research workflow. */
export const agentRoles = {
  literature: {
    description: "文献检索与研究现状",
    instruction: "Search and compare papers. Distinguish search leads, author claims and verified evidence. Return paper/source IDs and unresolved gaps.",
    tools: [...shared, ...research("search_papers", "search_arxiv", "search_library", "read_chunk", "list_papers", "get_paper_identity", "compare_papers", "find_code_links", "list_evidence", "read_research_map"), "web_search", "source_check", "fetch_content", "get_search_content"],
  },
  documents: {
    description: "文档导入、PDF 与本地 OCR",
    instruction: "Import and inspect documents. Use import_document with explicit ocr:true only when requested or necessary for a scanned PDF, and report extraction limitations and provenance. Return source/chunk IDs; do not treat OCR text as verified scientific evidence.",
    tools: [...shared, "read", ...research("list_files", "import_document", "download_arxiv", "search_library", "read_chunk", "list_evidence", "read_artifact", "list_papers", "get_paper_identity")],
  },
  code: {
    description: "工作区与论文代码分析",
    instruction: "Inspect project and pinned repository code, dependencies and APIs. Propose concrete changes with file/source references; the parent performs edits and executes checks.",
    tools: [...shared, "read", ...research("list_files", "search_code", "search_project", "inspect_symbols", "git_diff", "search_repositories", "inspect_repository", "read_repository_file", "find_code_links", "inspect_checkpoint"), "resolve-library-id", "query-docs"],
  },
  experiments: {
    description: "实验记录、指标与复现结果分析",
    instruction: "Analyze existing jobs, metrics and reproduction plans. Explain comparability, failures and uncertainty. Propose experiment specifications; only the parent may launch, cancel or modify experiments.",
    tools: [...shared, ...research("list_jobs", "job_status", "read_job_file", "list_experiments", "compare_experiments", "read_artifact", "read_reproduction_plan", "list_reproduction_plans", "read_research_map")],
  },
  memory: {
    description: "项目记忆与证据梳理",
    instruction: "Review current constraints, hypotheses, evidence and research maps. Identify contradictions and stale records. Suggest memory changes for the parent; never imply human confirmation.",
    tools: [...shared, ...research("list_evidence", "search_library", "read_chunk", "read_research_map", "list_papers", "get_paper_identity", "read_reproduction_plan", "list_reproduction_plans")],
  },
  review: {
    description: "依据核查与方法审阅",
    instruction: "Critically assess a proposed conclusion against available evidence, code and observed metrics. Return evidence IDs, weaknesses, counterexamples and what remains unverified. This is a model assessment, not scientific validation.",
    tools: [...shared, "read", ...research("list_evidence", "search_library", "read_chunk", "list_papers", "get_paper_identity", "compare_papers", "read_research_map", "compare_experiments", "list_experiments", "read_job_file", "search_code", "inspect_symbols", "read_reproduction_plan")],
  },
} as const;
export type AgentRole = keyof typeof agentRoles;
export const collaborationTools = ["agent_tasks", "agent_followup", "agent_status", "agent_cancel"] as const;
export function roleTools(role: AgentRole, active: readonly string[]): string[] {
  const available = new Set(active);
  return agentRoles[role].tools.filter(name => {
    if (!available.has(name)) return false;
    if (name.startsWith("mcp__research__")) return effects[name.slice("mcp__research__".length)] === "read";
    return true;
  });
}

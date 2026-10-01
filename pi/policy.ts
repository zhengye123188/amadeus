import { createHmac, randomUUID } from "node:crypto";
import { lstatSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { homedir } from "node:os";

export type Permission = "read-only" | "ask" | "workspace-write";
export type Effect = "read" | "write" | "execute" | "external";

// Local policy, not remote server annotations. Unknown operations fail closed.
export const effects: Record<string, Effect> = {
  search_papers: "read", import_document: "read", download_arxiv: "read",
  search_arxiv: "read", search_repositories: "read",
  inspect_repository: "read", read_repository_file: "read", find_code_links: "read",
  search_library: "read", read_chunk: "read", list_evidence: "read",
  save_evidence: "write", remember_research: "write", update_memory: "write",
  list_memory: "read", memory_context: "read", get_record: "read",
  link_repository: "write", project_status: "read", read_artifact: "read",
  list_jobs: "read", job_status: "read", read_job_file: "read", cancel_job: "write",
  run_experiment: "execute", index_embeddings: "external", hybrid_search: "external",
  jev_rerank: "external", list_files: "read", search_code: "read", git_diff: "read", load_skill: "read",
  backup_project: "write", project_data_info: "read",
};

const blocked = new Set([".git", ".research", ".pi", ".venv", "node_modules", "research.toml", "id_rsa", "id_ed25519"]);
function checkParts(path: string) {
  if (path.split(sep).some(p => blocked.has(p) || p.startsWith(".env") || /\.(pem|key)$/.test(p))) {
    throw new Error("Private state, environment, credentials or configuration path is blocked");
  }
}
export function safePath(workspace: string, value: unknown, write = false): string {
  if (typeof value !== "string" || value.includes("\0")) throw new Error("Expected a regular workspace path");
  const root = realpathSync(workspace), target = resolve(root, value);
  const credential = resolve(process.env.XDG_CONFIG_HOME || resolve(homedir(), ".config"), "research-cli", "api.json");
  let realCredential = credential;
  try { realCredential = realpathSync(credential); } catch { /* not configured yet */ }
  if (target === credential || target === realCredential) throw new Error("Saved API credentials are blocked");
  const inside = (p: string) => { const r = relative(root, p); return r !== ".." && !r.startsWith(".." + sep) && !isAbsolute(r); };
  if (!inside(target)) throw new Error("Path is outside the workspace");
  checkParts(relative(root, target));
  let ancestor = target;
  while (true) {
    try { lstatSync(ancestor); break; } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      ancestor = dirname(ancestor);
    }
  }
  const real = realpathSync(ancestor);
  if (real === realCredential) throw new Error("Saved API credentials are blocked");
  if (!inside(real)) throw new Error("Symlink escapes the workspace");
  checkParts(relative(root, real));
  if (ancestor === target) {
    const stat = statSync(target);
    if (!stat.isFile()) throw new Error("Only regular files are supported");
    if (write && stat.nlink > 1) throw new Error("Refusing to modify a hard-linked file");
  }
  return target;
}

export function approvalToken(secret: string, name: string, args: Record<string, unknown>): string {
  const payload = Buffer.from(JSON.stringify({ name, arguments: args, nonce: randomUUID(), expires: Math.floor(Date.now() / 1000) + 60 })).toString("base64url");
  return payload + "." + createHmac("sha256", secret).update(payload).digest("hex");
}

export function autoApprove(effect: Effect, permission: Permission, allowExperiments: boolean): boolean {
  if (effect === "read") return true;
  if (permission === "read-only") return false;
  return (effect === "write" && permission === "workspace-write") || (effect === "execute" && allowExperiments);
}

export function plain(value: string): string {
  return value.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, "");
}

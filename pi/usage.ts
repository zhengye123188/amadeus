import { appendFileSync, closeSync, constants, existsSync, fstatSync, lstatSync, mkdirSync, openSync, realpathSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export interface UsageRecord {
  session_id: string;
  model: string;
  provider: string;
  category: "generation" | "compaction";
  tokens: { input: number; output: number; cacheRead: number; cacheWrite: number };
  estimated_cost_usd: number | null;
  pricing_source: "configured_profile" | "provider_catalog";
}

export interface PackageUsageRecord {
  session_id: string;
  source: string;
  tool: string;
}

/** Audit numeric usage only. Do not store prompts, credentials or transport headers. */
export function recordUsage(workspace: string, record: UsageRecord): void {
  appendLedger(workspace, record);
}

/** Separate service calls have unknown prices; never add them to model-token totals. */
export function recordPackageUsage(workspace: string, record: PackageUsageRecord): void {
  appendLedger(workspace, { ...record, category: "package-tool", estimated_cost_usd: null });
}

function appendLedger(workspace: string, record: object): void {
  const root = realpathSync(workspace), state = join(root, ".research");
  if (existsSync(state) && (lstatSync(state).isSymbolicLink() || realpathSync(state) !== resolve(state))) throw new Error("Usage directory may not be a symlink");
  mkdirSync(state, { recursive: true, mode: 0o700 });
  const path = join(state, "usage.jsonl");
  let handle: number;
  try { handle = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_APPEND | constants.O_NOFOLLOW, 0o600); }
  catch { throw new Error("Expected a private regular usage ledger"); }
  try {
    const info = fstatSync(handle);
    if (!info.isFile() || info.nlink !== 1) throw new Error("Expected a private regular usage ledger");
    if (info.size > 50_000_000) throw new Error("Usage ledger exceeds 50 MB; archive it before continuing");
    appendFileSync(handle, JSON.stringify({ timestamp: Date.now() / 1000, ...record }) + "\n");
  } finally { closeSync(handle); }
}

export function positiveBudget(value: string | undefined, name: string, integer = false): number | undefined {
  if (value === undefined) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0 || integer && !Number.isInteger(parsed)) throw new Error(`Invalid ${name}; expected a positive ${integer ? "integer" : "number"}`);
  return parsed;
}

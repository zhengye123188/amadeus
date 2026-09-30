/** --live is opt-in: the default exercises real Pi with a deterministic local provider fixture. */
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { mockEndpoint, ResearchProcess } from "../tests/pi/harness.ts";
import { MEMORY_MARKER } from "../pi/memory.ts";

const live = process.argv.includes("--live");
if (live && (!process.env.OPENAI_API_KEY || !process.env.OPENAI_BASE_URL || !process.env.RESEARCH_MODEL)) {
  throw new Error("Live evaluation requires OPENAI_API_KEY, OPENAI_BASE_URL and RESEARCH_MODEL; it makes billable model requests.");
}
const outputIndex = process.argv.indexOf("--output");
const output = resolve(outputIndex >= 0 ? process.argv[outputIndex + 1] : "evals/results/local-memory.json");
const cases = JSON.parse(readFileSync("evals/memory-cases.json", "utf8")) as Array<{id: string; constraint: string; hypothesis: string; quote: string}>;
const rows: unknown[] = [];
const root = mkdtempSync(join(tmpdir(), "research-eval-"));
try {
  for (const item of cases) {
    for (const mode of ["off", "on"]) {
      const dir = join(root, `${item.id}-${mode}`), workspace = join(dir, "work"), agentDir = join(dir, "agent");
      mkdirSync(workspace, { recursive: true }); mkdirSync(agentDir);
      writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ compaction: { enabled: false, reserveTokens: 4096, keepRecentTokens: 100 }, retry: { enabled: false } }));
      const seed = spawnSync(process.env.RESEARCH_PYTHON || resolve(".venv/bin/python"), ["scripts/seed_memory_eval.py", workspace], { input: JSON.stringify(item), encoding: "utf8" });
      if (seed.status !== 0) throw new Error(seed.stderr);
      const ids = JSON.parse(seed.stdout);
      // The fixture deliberately loses old details during compaction. This verifies plumbing,
      // not model quality: a real model with the same tools may retrieve them in either arm.
      const endpoint = live ? undefined : await mockEndpoint(request => {
        const context = JSON.stringify(request.messages);
        if (!request.tools?.length) return { text: "Synthetic compacted summary: research remains in progress." };
        if (context.includes("FINAL_RECALL")) {
          const visible = context.includes(MEMORY_MARKER);
          return { text: JSON.stringify({ constraint: visible ? item.constraint : "unknown", hypothesis_status: visible ? "proposed" : "unknown", evidence_quote: visible ? item.quote : "unknown", failed_job_id: visible ? ids.job_id : "unknown" }) };
        }
        return { text: "Synthetic conversation fixture acknowledged." };
      });
      const app = new ResearchProcess(workspace, agentDir, endpoint?.url || process.env.OPENAI_BASE_URL!, ["--memory", mode, "--max-turns", "16", "--max-seconds", "120"], live ? { OPENAI_API_KEY: process.env.OPENAI_API_KEY!, RESEARCH_MODEL: process.env.RESEARCH_MODEL! } : {});
      const started = Date.now();
      let record: Record<string, unknown>;
      try {
        await app.prompt("This workspace already contains synthetic research records. We will discuss related work; acknowledge without running experiments.");
        await app.prompt("Discuss general evaluation methodology briefly. " + "Keep baseline, validation and held-out testing separate. ".repeat(30));
        await app.command("compact");
        await app.prompt('FINAL_RECALL: Using this project’s records, return only JSON with fields constraint (exact constraint text), hypothesis_status, evidence_quote (exact saved quote), failed_job_id. Recover missing information with available tools. Do not invent facts or start experiments.');
        const last = await app.command("get_last_assistant_text");
        const stats = await app.command("get_session_stats");
        let answer: any = {};
        try { answer = JSON.parse(last.text.replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { /* malformed output is a recorded failure */ }
        record = { case: item.id, memory: mode, metrics: {
          constraint_exact: answer.constraint === item.constraint,
          hypothesis_status_correct: answer.hypothesis_status === "proposed",
          evidence_quote_exact: answer.evidence_quote === item.quote,
          failed_job_recovered: answer.failed_job_id === ids.job_id,
        }, answer, stats, elapsed_ms: Date.now() - started };
      } catch (error) { record = { case: item.id, memory: mode, error: String(error), elapsed_ms: Date.now() - started }; }
      finally { await app.close(); await endpoint?.close(); }
      rows.push(record);
      console.log(`${item.id} memory=${mode}: ${JSON.stringify(record.metrics || record.error)}`);
    }
  }
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, JSON.stringify({ mode: live ? "live_model" : "deterministic_mechanism_fixture", date: new Date().toISOString(),
    model: live ? process.env.RESEARCH_MODEL : "local-fixture", cases: cases.length, repetitions: 1,
    caveat: live ? "Small synthetic evaluation; exact field checks are not scientific task success. Inspect answers and repeat runs. Custom endpoint prices are unconfigured, not zero cost." : "The mock provider is programmed to recall injected memory. These results only verify Pi/MCP/compaction plumbing and must not be claimed as a quality improvement over Pi.",
    rows }, null, 2) + "\n");
  console.log(`Saved ${output}`);
  if (rows.some(row => Boolean((row as {error?: unknown}).error))) process.exitCode = 1;
} finally { rmSync(root, { recursive: true, force: true }); }

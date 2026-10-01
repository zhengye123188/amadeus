import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync, mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { positiveBudget, recordUsage } from "../../pi/usage.ts";
import { selectedInstructions, selectedSkillFiles } from "../../pi/trust.ts";

test("usage ledger keeps unknown cost and rejects symlink targets", () => {
  const root = mkdtempSync(join(tmpdir(), "research-usage-"));
  const record = { session_id: "fixture", model: "fixture", provider: "research-endpoint", category: "generation" as const, tokens: { input: 12, output: 3, cacheRead: 0, cacheWrite: 0 }, estimated_cost_usd: null, pricing_source: "configured_profile" as const };
  try {
    recordUsage(root, record);
    const path = join(root, ".research", "usage.jsonl");
    assert.equal(JSON.parse(readFileSync(path, "utf8")).estimated_cost_usd, null);
    rmSync(path);
    symlinkSync(join(root, "outside"), path);
    assert.throws(() => recordUsage(root, record), /regular/);
    assert.throws(() => positiveBudget("NaN", "budget"), /positive/);
    assert.throws(() => positiveBudget("1.5", "budget", true), /integer/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("project instructions and skills require explicit selection", () => {
  const root = mkdtempSync(join(tmpdir(), "research-trust-"));
  try {
    const folder = join(root, "skills"); mkdirSync(folder);
    const skill = join(folder, "SKILL.md"); writeFileSync(skill, "# Selected skill");
    const instructions = join(root, "AGENTS.md"); writeFileSync(instructions, "Use CPU only.");
    assert.equal(selectedInstructions(undefined), undefined);
    assert.equal(selectedSkillFiles(undefined).size, 0);
    assert.equal(selectedInstructions(instructions), "Use CPU only.");
    assert(selectedSkillFiles(JSON.stringify([folder])).has(realpathSync(skill)));
    writeFileSync(instructions, Buffer.alloc(32001));
    assert.throws(() => selectedInstructions(instructions), /32 KB/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

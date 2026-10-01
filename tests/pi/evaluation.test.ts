import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gradeReport, loadCases, runEvaluation } from "../../scripts/eval-research.ts";

test("research case suite covers artifact, evidence, experiment and constraint tasks", () => {
  const cases = loadCases();
  assert(cases.length >= 10 && cases.length <= 20);
  assert.equal(new Set(cases.map(item => item.id)).size, cases.length);
  assert(cases.every(item => item.fields.length && item.required_tools.length));
  for (const id of ["exact-quote", "negative-result", "protocol-mismatch", "retry-deduplication", "untrusted-source", "comparison-artifact"]) assert(cases.some(item => item.id === id));
  const fixture = { quote: "expected exact quotation", source_id: "source", evidence_id: "evidence", jobs: {}, comparisons: { quadratic: { metrics: { mse: { baseline: {}, candidate: {} } } }, negative: { metrics: { mse: {} } } } };
  const item = cases.find(item => item.id === "exact-quote")!;
  const state = { jobs: [], sources: [{ source_id: "source" }], evidence: [{ evidence_id: "evidence" }], memory: [], artifacts: [] };
  const forged = gradeReport(item, { case_id: item.id, quote: "invented quote", source_id: "source", evidence_id: "evidence", scientifically_confirmed: true, references: ["unknown"], limitations: "Synthetic scope with uncertainty." }, fixture, [], state, 0);
  assert.equal(forged.passed, false);
  assert.equal(forged.checks.references_resolve, false);
  assert.equal(forged.checks.field_quote, false);
  assert.equal(forged.checks.field_scientifically_confirmed, false);
  const fromContext = gradeReport(item, { case_id: item.id, quote: fixture.quote, source_id: "source", evidence_id: "evidence", scientifically_confirmed: false, references: ["evidence"], limitations: "Synthetic scope with uncertainty." }, fixture, [], state, 0);
  assert.equal(fromContext.passed, true, "Valid source-backed output may use already injected context without repeating a retrieval tool");
  assert.equal(fromContext.trajectory.suggested_path_observed, false);
  assert.equal("tool_path" in fromContext.checks, false);
});

test("retry task requires an observed successful deduplicated call rather than only a report assertion", () => {
  const item = loadCases().find(item => item.id === "retry-deduplication")!;
  const job = { job_id: "existing-job", request_id: "same-request" };
  const fixture = { jobs: { baseline: [job] }, comparisons: { quadratic: { metrics: { mse: {} } }, negative: { metrics: { mse: {} } } } };
  const state = { jobs: [job], sources: [], evidence: [], memory: [], artifacts: [] };
  const report = { case_id: item.id, job_id: job.job_id, deduplicated: true, references: [job.job_id], limitations: "Synthetic execution-only fixture; no scientific claim." };
  const absent = gradeReport(item, report, fixture, [], state, 1);
  assert.equal(absent.passed, false);
  assert.equal(absent.checks.retry_actually_deduplicated, false);
  const events = [
    { type: "tool_execution_start", toolName: "mcp__research__run_experiment", toolCallId: "retry", args: { request_id: job.request_id } },
    { type: "tool_execution_end", toolName: "mcp__research__run_experiment", toolCallId: "retry", isError: false, result: { content: [{ type: "text", text: JSON.stringify({ ok: true, result: { job_id: job.job_id, deduplicated: true } }) }] } },
  ];
  assert.equal(gradeReport(item, report, fixture, events, state, 1).passed, true);
  Object.assign(events[1].result!, { structuredContent: { content: events[1].result!.content } });
  assert.equal(gradeReport(item, report, fixture, events, state, 1).passed, true, "Pi's native structured wrapper must fall back to the actual MCP JSON content");
});

test("real Pi research smoke persists report artifacts and provenance equally in memory arms", { timeout: 90000 }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "research-evaluation-test-"));
  const output = join(directory, "report.json");
  try {
    const result = await runEvaluation({ output, caseIds: ["exact-quote", "comparison-artifact"] });
    assert.equal(result.mode, "scripted_mechanism_smoke");
    assert.equal(result.rows.length, 4);
    assert(result.rows.every(row => row.passed), JSON.stringify(result.rows));
    assert.equal(result.summary.off.success_rate, 1);
    assert.equal(result.summary.on.success_rate, 1);
    assert(result.rows.every(row => row.cost.model_usd === null));
    assert(result.rows.every(row => row.artifact_sha256.length === 64));
    for (const row of result.rows) {
      const events = readFileSync(join(row.raw_trace_directory, "events.jsonl"), "utf8");
      assert(events.includes("tool_execution_end"));
      const answer = JSON.parse(readFileSync(join(row.raw_trace_directory, "workspace", "evaluation-answer.json"), "utf8"));
      assert.equal(answer.case_id, row.case);
    }
    assert.equal(JSON.parse(readFileSync(output, "utf8")).mode, result.mode);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { mockEndpoint, ResearchProcess, toolResults } from "./harness.ts";

test("real Pi: all six native package tools load and Context7 runs through the CLI", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-native-cli-"));
  const preload = join(root, "context7-fixture.mjs");
  writeFileSync(preload, `import {existsSync, writeFileSync} from 'node:fs';
const original = globalThis.fetch;
const fixtureFetch = (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input));
  if (url.hostname !== 'context7.com') {
    if (url.hostname !== '127.0.0.1') throw new Error('Unexpected external request in fixture');
    return original(input, init);
  }
  if (!init.signal) throw new Error('Native cancellation signal is missing');
  if (url.pathname === '/api/v2/libs/search') return Promise.resolve(Response.json({results:[{id:'/pytorch/pytorch',title:'PyTorch',description:'Tensor library',totalSnippets:20,trustScore:9,versions:['2.0']}]}));
  if (url.pathname === '/api/v2/context') return Promise.resolve(new Response('Use torch.autograd.grad to compute derivatives.'));
  throw new Error('Unexpected Context7 fixture route');
};
// Pi installs its HTTP globals during startup. Override only after its core is loaded.
if (process.env.RESEARCH_STARTUP_FILE) {
  const timer=setInterval(()=>{
    if (!existsSync(process.env.RESEARCH_STARTUP_FILE)) return;
    globalThis.fetch=fixtureFetch;
    writeFileSync(process.env.FIXTURE_FETCH_READY,'ready');
    clearInterval(timer);
  }, 1);
  timer.unref();
}`);
  let step = 0;
  const endpoint = await mockEndpoint(request => {
    if (step++ === 0) {
      assert.equal(readFileSync(join(root, "fetch-ready"), "utf8"), "ready");
      const tools = request.tools?.map(tool => tool.function.name) || [];
      assert.equal(tools.length, 62);
      for (const name of ["read", "write", "edit", "web_search", "fetch_content", "source_check", "get_search_content", "resolve-library-id", "query-docs", "mcp__research__save_evidence"]) assert(tools.includes(name), name);
      assert(!tools.includes("bash"));
      return { tool: "resolve-library-id", args: { query: "tensor derivatives", libraryName: "pytorch" } };
    }
    const results = toolResults(request);
    if (step === 2) {
      assert(JSON.stringify(results).includes("/pytorch/pytorch"));
      return { tool: "query-docs", args: { libraryId: "/pytorch/pytorch", query: "autograd" } };
    }
    assert(JSON.stringify(results).includes("torch.autograd.grad"));
    return { text: "Native documentation tools completed." };
  });
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url, [], {
    RESEARCH_OFFLINE: "0", XDG_CONFIG_HOME: join(root, "config"), XDG_DATA_HOME: join(root, "data"),
    CONTEXT7_API_KEY: "ctx7sk-fixture-not-a-real-key",
    FIXTURE_FETCH_READY: join(root, "fetch-ready"),
    NODE_OPTIONS: `${process.env.NODE_OPTIONS || ""} --import=${pathToFileURL(preload).href}`,
  });
  try {
    await app.prompt("Find PyTorch and read autograd documentation.");
    const results = app.events.filter(event => event.type === "tool_execution_end");
    assert.equal(results.length, 2, JSON.stringify(results));
    assert(results.every(event => !event.isError), JSON.stringify(results));
    const rows = readFileSync(join(root, ".research", "usage.jsonl"), "utf8").trim().split("\n").map(row => JSON.parse(row));
    assert.equal(rows.filter(row => row.category === "generation").length, 3);
    assert.equal(rows.filter(row => row.category === "package-tool").length, 2);
    assert(!JSON.stringify(rows).includes("ctx7sk"));
    assert(!JSON.stringify(rows).includes("tensor derivatives"));
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: offline mode omits native network tools and keeps local cache lookup", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-native-offline-"));
  const endpoint = await mockEndpoint(request => {
    const tools = request.tools?.map(tool => tool.function.name) || [];
    assert(tools.includes("get_search_content"));
    assert(tools.includes("mcp__research__project_status"));
    for (const name of ["web_search", "source_check", "fetch_content", "resolve-library-id", "query-docs", "bash"]) assert(!tools.includes(name), name);
    return { text: "Offline package selection checked." };
  });
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url, [], {
    XDG_CONFIG_HOME: join(root, "config"), XDG_DATA_HOME: join(root, "data"),
  });
  try { await app.prompt("Check the offline tool set."); }
  finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

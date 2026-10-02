import { after, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { tsImport } from "tsx/esm/api";
import { loadPackageSelection } from "../bin/packages.mjs";

const { preparePackageTools, packageToolArguments } = await tsImport("../pi/packages.ts", import.meta.url);
const { default: research } = await tsImport("../pi/research.ts", import.meta.url);
const checkout = fileURLToPath(new URL("../", import.meta.url));
const suite = realpathSync(mkdtempSync(join(tmpdir(), "research-package-tools-")));
const originalFetch = globalThis.fetch, originalAgentDir = process.env.PI_CODING_AGENT_DIR;
process.env.PI_CODING_AGENT_DIR = join(suite, "agent");
// scopeFetch captures this dispatcher once. Individual tests swap its implementation,
// preserving the real adapter's AsyncLocalStorage wrapper and never contacting a service.
let fetchImplementation;
globalThis.fetch = (...args) => fetchImplementation(...args);
beforeEach(() => { fetchImplementation = () => { throw new Error("Unexpected network request in package fixture"); }; });
after(() => {
  globalThis.fetch = originalFetch;
  if (originalAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
  else process.env.PI_CODING_AGENT_DIR = originalAgentDir;
  rmSync(suite, { recursive: true, force: true });
});

function piFixture() {
  const tools = new Map(), commands = new Map(), handlers = new Map(), messages = [], entries = [];
  const pi = {
    events: new EventEmitter(),
    registerTool(tool) { tools.set(tool.name, tool); },
    registerCommand(name, command) { commands.set(name, command); },
    on(name, handler) { const list = handlers.get(name) || []; list.push(handler); handlers.set(name, list); return () => {}; },
    appendEntry(name, value) { entries.push({ name, value }); },
    sendMessage(message) { messages.push(message); },
    registerFlag() {}, registerShortcut() {}, registerProvider() {}, registerMcpServer() {}, registerVirtualModel() {},
    getMcpServers() { return []; },
    getAllTools() { return [...tools.values()]; },
    getActiveTools() { return [...tools.keys()]; },
    setActiveTools() {}, getSettings() { return {}; },
  };
  return { pi, tools, commands, handlers, messages, entries };
}

function context(cwd, { hasUI = false, signal = new AbortController().signal, confirm = async () => true } = {}) {
  return {
    cwd, hasUI, signal,
    sessionManager: { getSessionId: () => "package-fixture", getBranch: () => [] },
    ui: { confirm, notify() {}, setStatus() {}, select: async () => undefined },
    modelRegistry: { getAll: () => [], find: () => undefined },
  };
}

function workdir() { return realpathSync(mkdtempSync(join(suite, "workspace-"))); }

function selectedFixture(code, effects = { fixture_read: "read" }, networkTools = []) {
  const directory = workdir(), path = join(directory, "extension.mjs"), source = directory;
  writeFileSync(path, code);
  return {
    directory,
    selection: {
      extensions: [{ path, source, effects, networkTools }], skills: [], disabledResearchTools: [],
      policies: Object.fromEntries(Object.entries(effects).map(([name, effect]) => [name, { source, effect, network: networkTools.includes(name) }])),
      agentDir: join(directory, "agent"), configFile: join(directory, "packages.json"),
    },
  };
}

function toolCode(name, body = "return {content:[{type:'text',text:'fixture'}],details:{called:true}};") {
  return `pi.registerTool({name:${JSON.stringify(name)},label:'Fixture',description:'Fixture',parameters:{type:'object',properties:{}},async execute(callId,args,signal,onUpdate,ctx){${body}}});`;
}

async function defaults(offline = false) {
  const selection = await loadPackageSelection({ root: checkout, cwd: suite, env: { XDG_CONFIG_HOME: join(suite, "config"), XDG_DATA_HOME: join(suite, "data") } });
  const fixture = piFixture();
  const adapter = await preparePackageTools(fixture.pi, selection, { offline, authorize: async () => true });
  adapter.register();
  return { ...fixture, adapter, selection };
}

test("the actual bundled factories load exactly six native tools without commands or an extra agent loop", async () => {
  const fixture = await defaults();
  assert.deepEqual([...fixture.tools.keys()].sort(), ["web_search", "source_check", "fetch_content", "get_search_content", "resolve-library-id", "query-docs"].sort());
  assert.equal(fixture.commands.size, 0);
  assert([...fixture.handlers.keys()].every(event => ["session_start", "session_tree", "session_shutdown"].includes(event)));
  assert.equal(fixture.tools.has("web_enable"), false);
  assert.equal(fixture.tools.get("web_search").parameters.properties.workflow, undefined);
  assert.equal(fixture.tools.get("web_search").parameters.properties.includeContent, undefined);
  assert.equal(fixture.tools.get("fetch_content").parameters.properties.auth, undefined);
  assert.deepEqual(fixture.tools.get("fetch_content").parameters.properties.mode.enum, ["readable", "raw"]);
  assert.equal(fixture.tools.get("query-docs").annotations.readOnlyHint, true);
});

test("real Context7 search and docs tools send the expected requests and record service calls separately", async () => {
  const fixture = await defaults(), directory = workdir(), requests = [];
  const originalKey = process.env.CONTEXT7_API_KEY;
  process.env.CONTEXT7_API_KEY = "ctx7sk-fixture-not-a-real-key";
  try {
    fetchImplementation = async (input, init) => {
      const url = new URL(String(input));
      assert.equal(url.origin, "https://context7.com");
      assert(init.signal instanceof AbortSignal);
      assert.equal(new Headers(init.headers).get("authorization"), "Bearer ctx7sk-fixture-not-a-real-key");
      requests.push(url);
      if (url.pathname.endsWith("/libs/search")) return Response.json({ results: [{ id: "/pytorch/pytorch", title: "PyTorch", description: "Tensor library", totalSnippets: 20, trustScore: 9, versions: ["2.0"] }] });
      assert.equal(url.pathname, "/api/v2/context");
      return new Response("Use torch.autograd.grad to compute derivatives.");
    };
    const ctx = context(directory), signal = new AbortController().signal;
    const libraries = await fixture.tools.get("resolve-library-id").execute("search", { query: "tensor derivatives", libraryName: "pytorch" }, signal, undefined, ctx);
    assert.match(libraries.content[0].text, /\/pytorch\/pytorch/);
    const docs = await fixture.tools.get("query-docs").execute("docs", { query: "autograd", libraryId: "/pytorch/pytorch" }, signal, undefined, ctx);
    assert.match(docs.content[0].text, /torch\.autograd\.grad/);
    assert.equal(requests[0].searchParams.get("libraryName"), "pytorch");
    assert.equal(requests[1].searchParams.get("libraryId"), "/pytorch/pytorch");
    const ledger = readFileSync(join(directory, ".research", "usage.jsonl"), "utf8").trim().split("\n").map(row => JSON.parse(row));
    assert.equal(ledger.length, 2);
    assert(ledger.every(row => row.category === "package-tool" && row.estimated_cost_usd === null));
    assert.equal(JSON.stringify(ledger).includes("ctx7sk"), false);
    assert.equal(JSON.stringify(ledger).includes("tensor derivatives"), false);
  } finally {
    if (originalKey === undefined) delete process.env.CONTEXT7_API_KEY;
    else process.env.CONTEXT7_API_KEY = originalKey;
  }
});

test("Context7 cancellation reaches fetch although the upstream tool does not accept a signal", async () => {
  const fixture = await defaults(), directory = workdir(), controller = new AbortController();
  let receivedSignal, started;
  const requestStarted = new Promise(resolve => { started = resolve; });
  fetchImplementation = (_input, init) => new Promise((_resolve, reject) => {
    receivedSignal = init.signal;
    init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    started();
  });
  const pending = fixture.tools.get("query-docs").execute("cancel", { libraryId: "/pytorch/pytorch", query: "cancel fixture" }, controller.signal, undefined, context(directory, { signal: controller.signal }));
  const rejected = assert.rejects(pending, /fixture cancelled/);
  await requestStarted;
  controller.abort(new Error("fixture cancelled"));
  await rejected;
  assert.equal(receivedSignal.aborted, true);
});

test("cancelling one concurrent native request leaves the other request's signal active", async () => {
  const fixture = await defaults(), directory = workdir(), first = new AbortController(), second = new AbortController(), requests = new Map();
  let started;
  const bothStarted = new Promise(resolve => { started = resolve; });
  fetchImplementation = (input, init) => new Promise((resolve, reject) => {
    requests.set(new URL(String(input)).searchParams.get("query"), { signal: init.signal, resolve });
    init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    if (requests.size === 2) started();
  });
  const tool = fixture.tools.get("query-docs");
  const cancelled = tool.execute("first", { libraryId: "/pytorch/pytorch", query: "first" }, first.signal, undefined, context(directory));
  const rejected = assert.rejects(cancelled, /cancel first only/);
  const remaining = tool.execute("second", { libraryId: "/pytorch/pytorch", query: "second" }, second.signal, undefined, context(directory));
  await bothStarted;
  first.abort(new Error("cancel first only"));
  await rejected;
  assert.equal(requests.get("second").signal.aborted, false);
  requests.get("second").resolve(new Response("Second request completed."));
  assert.equal((await remaining).content[0].text, "Second request completed.");
});

test("offline registration removes network tools while preserving local stored-content lookup", async () => {
  const fixture = await defaults(true);
  assert.deepEqual([...fixture.tools.keys()], ["get_search_content"]);
  assert.equal(fixture.adapter.policies["query-docs"], undefined);
  const selected = selectedFixture(`export default pi => {${toolCode("fixture_read")}};`);
  const local = piFixture();
  const adapter = await preparePackageTools(local.pi, selected.selection, { offline: true, authorize: async () => true });
  adapter.register();
  const result = await local.tools.get("fixture_read").execute("read", {}, new AbortController().signal, undefined, context(selected.directory));
  assert.equal(result.details.called, true);
});

test("native adapter ignores unselected tools, commands, event hooks and prototype property names", async () => {
  const selected = selectedFixture(`export default pi => {
    ${toolCode("fixture_read")}
    ${toolCode("unselected_tool")}
    ${toolCode("toString")}
    pi.registerCommand('unselected-command',{handler(){throw new Error('must not run')}});
    pi.on('before_agent_start',()=>{throw new Error('must not run')});
  };`);
  const fixture = piFixture();
  const adapter = await preparePackageTools(fixture.pi, selected.selection, { offline: false, authorize: async () => true });
  adapter.register();
  assert.deepEqual([...fixture.tools.keys()], ["fixture_read"]);
  assert.equal(fixture.commands.size, 0);
  assert.equal(fixture.handlers.size, 0);
});

test("reserved registrations, duplicate registrations and missing selected tools fail before registration", async () => {
  for (const name of ["read", "bash", "mcp__research__save_evidence", "constructor", "__proto__"]) {
    const selected = selectedFixture(`export default pi => {${toolCode("fixture_read")}${toolCode(name)}};`);
    const fixture = piFixture();
    await assert.rejects(() => preparePackageTools(fixture.pi, selected.selection, { offline: false, authorize: async () => true }), /reserved/);
    assert.equal(fixture.tools.size, 0);
  }
  const duplicate = selectedFixture(`export default pi => {${toolCode("fixture_read")}${toolCode("fixture_read")}};`);
  await assert.rejects(() => preparePackageTools(piFixture().pi, duplicate.selection, { offline: false, authorize: async () => true }), /Duplicate/);
  const missing = selectedFixture("export default () => {}; ");
  await assert.rejects(() => preparePackageTools(piFixture().pi, missing.selection, { offline: false, authorize: async () => true }), /did not register/);
});

test("a signal cancelled before execution cannot invoke an upstream tool with side effects", async () => {
  const selected = selectedFixture(`import {writeFileSync} from 'node:fs'; import {join} from 'node:path'; export default pi => {${toolCode("fixture_read", "writeFileSync(join(ctx.cwd,'cancelled-side-effect.txt'),'unexpected'); return {content:[],details:{}};")}};`);
  const fixture = piFixture(), controller = new AbortController();
  const adapter = await preparePackageTools(fixture.pi, selected.selection, { offline: false, authorize: async () => true });
  adapter.register();
  controller.abort(new Error("already cancelled"));
  await assert.rejects(() => fixture.tools.get("fixture_read").execute("cancelled", {}, controller.signal, undefined, context(selected.directory)), /already cancelled/);
  assert.equal(existsSync(join(selected.directory, "cancelled-side-effect.txt")), false);
});

async function withEnvironment(values, task) {
  const original = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]));
  for (const [key, value] of Object.entries(values)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  try { return await task(); }
  finally { for (const [key, value] of Object.entries(original)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } }
}

test("Research permissions gate package writes and execution through the actual native wrapper", async () => {
  const selected = selectedFixture(`import {writeFileSync} from 'node:fs'; import {join} from 'node:path'; export default pi => {
    ${toolCode("fixture_write", "writeFileSync(join(ctx.cwd,'written.txt'),'approved'); return {content:[],details:{}};")}
    ${toolCode("fixture_execute", "writeFileSync(join(ctx.cwd,'executed.txt'),'approved'); return {content:[],details:{}};")}
  };`, { fixture_write: "write", fixture_execute: "execute" });
  for (const scenario of [
    { permission: undefined, execution: "local", experiments: "0", write: false, execute: false },
    { permission: "read-only", execution: "local", experiments: "1", write: false, execute: false },
    { permission: "ask", execution: "local", experiments: "0", write: false, execute: false },
    { permission: "workspace-write", execution: "disabled", experiments: "1", write: true, execute: false },
    { permission: "workspace-write", execution: "local", experiments: "0", write: true, execute: false },
    { permission: "workspace-write", execution: "local", experiments: "1", write: true, execute: true },
  ]) {
    const directory = workdir();
    await withEnvironment({ RESEARCH_PYTHON: "/fixture/not-started-python", RESEARCH_PACKAGE_SELECTION: JSON.stringify(selected.selection), RESEARCH_PERMISSION: scenario.permission, RESEARCH_EXECUTION: scenario.execution, RESEARCH_APPROVE_EXPERIMENTS: scenario.experiments, RESEARCH_OFFLINE: "0", RESEARCH_MODEL_PROFILE: undefined, RESEARCH_STARTUP_FILE: undefined, RESEARCH_STARTUP_TOKEN: undefined, OPENAI_BASE_URL: undefined, RESEARCH_MODEL: undefined }, async () => {
      const fixture = piFixture();
      await research(fixture.pi);
      const ctx = context(directory);
      for (const [name, allowed, file] of [["fixture_write", scenario.write, "written.txt"], ["fixture_execute", scenario.execute, "executed.txt"]]) {
        const invoked = fixture.tools.get(name).execute(name, {}, ctx.signal, undefined, ctx);
        if (allowed) await invoked;
        else await assert.rejects(invoked, /permission denied/);
        assert.equal(existsSync(join(directory, file)), allowed);
      }
    });
  }
  await withEnvironment({ RESEARCH_PYTHON: "/fixture/not-started-python", RESEARCH_PACKAGE_SELECTION: JSON.stringify(selected.selection), RESEARCH_PERMISSION: "ask", RESEARCH_EXECUTION: "local", RESEARCH_APPROVE_EXPERIMENTS: "0", RESEARCH_OFFLINE: "0", OPENAI_BASE_URL: undefined, RESEARCH_MODEL: undefined }, async () => {
    const fixture = piFixture(), directory = workdir(), dialogs = [];
    await research(fixture.pi);
    const ctx = context(directory, { hasUI: true, confirm: async (title) => { dialogs.push(title); return true; } });
    const hook = fixture.handlers.get("tool_call")[0];
    await hook({ toolName: "fixture_write", input: {} }, ctx);
    assert.equal(dialogs.length, 0, "The tool-call hook delegates the one approval to the native execute wrapper");
    await fixture.tools.get("fixture_write").execute("write", {}, ctx.signal, undefined, ctx);
    assert.equal(dialogs.length, 1);
    assert.equal(existsSync(join(directory, "written.txt")), true);
  });
});

test("web wrappers reject hidden workflows, auth, unpinned code and non-page retrieval parameters", () => {
  const source = "npm:pi-web-access@0.35.0";
  const safe = packageToolArguments(source, "web_search", { query: "research agent" });
  assert.equal(safe.workflow, "none");
  assert.equal(safe.includeContent, false);
  const invalid = [
    ["web_search", { query: "x", workflow: "summary-review" }],
    ["web_search", { query: "x", includeContent: true }],
    ["web_search", { queries: ["a", "b", "c", "d", "e"] }],
    ["web_search", { query: "x", proxy: "http://example.com" }],
    ["source_check", { claim: "x", fetchContent: true }],
    ["source_check", { claim: "x", proxy: "http://example.com" }],
    ["fetch_content", { url: "https://example.com", auth: true }],
    ["fetch_content", { url: "https://example.com", forceClone: false }],
    ["fetch_content", { url: "https://example.com", mode: "answer" }],
    ["fetch_content", { url: "https://example.com", timestamp: "10" }],
    ["fetch_content", { url: "https://example.com", model: "any" }],
    ["fetch_content", { url: "https://example.com", proxy: "" }],
    ["fetch_content", { url: "file:///private/example" }],
    ["fetch_content", { url: "https://private:credential@example.com" }],
    ["fetch_content", { url: "https://github.com/owner/repo" }],
    ["fetch_content", { url: "https://api.github.com/repos/owner/repo/contents/readme" }],
    ["fetch_content", { url: "https://raw.githubusercontent.com/owner/repo/main/readme" }],
    ["fetch_content", { url: "https://gist.github.com/owner/id" }],
    ["fetch_content", { url: "https://example.com/article.pdf?download=true" }],
    ["fetch_content", { url: "https://arxiv.org/pdf/2401.00001" }],
    ["fetch_content", { urls: Array(6).fill("https://example.com") }],
  ];
  for (const [name, args] of invalid) assert.throws(() => packageToolArguments(source, name, args), undefined, `${name}: ${JSON.stringify(args)}`);
  assert.equal(packageToolArguments(source, "fetch_content", { url: "https://docs.python.org/3/", mode: "readable" }).mode, "readable");
});

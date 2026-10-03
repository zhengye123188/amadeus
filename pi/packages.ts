import { AsyncLocalStorage } from "node:async_hooks";
import { createJiti } from "jiti";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { PackagePolicy, PackageSelection, SelectedPackageExtension } from "../bin/packages.mjs";
import { packageModuleAliases } from "../bin/packages.mjs";
import { recordPackageUsage } from "./usage.ts";

const reserved = new Set(["read", "write", "edit", "bash", "powershell", "grep", "find", "ls", "codemode", "tool_search", "agent_tasks", "agent_followup", "agent_status", "agent_cancel", "constructor", "__proto__", "prototype"]);
const requestScope = new AsyncLocalStorage<AbortSignal>();
let scopedFetch: typeof fetch | undefined;

/** Apply cancellation even to packages whose fetch implementation ignores the tool signal. */
function scopeFetch(): void {
  if (globalThis.fetch === scopedFetch) return;
  const fetch = globalThis.fetch;
  globalThis.fetch = ((input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    const signal = requestScope.getStore();
    if (!signal) return fetch(input, init);
    const requestSignal = input instanceof Request ? input.signal : undefined;
    const signals = [signal, init?.signal, requestSignal].filter((item): item is AbortSignal => Boolean(item));
    return fetch(input, { ...init, signal: AbortSignal.any(signals) });
  }) as typeof fetch;
  scopedFetch = globalThis.fetch;
}

export function packageToolArguments(source: string, name: string, args: Record<string, unknown>): Record<string, unknown> {
  if (source !== "npm:pi-web-access@0.35.0") return args;
  if (args.proxy !== undefined) throw new Error("Per-call web proxies are unavailable in Amadeus");
  if (name === "web_search") {
    if (Array.isArray(args.queries) && args.queries.length > 4) throw new Error("Use at most four web search queries per call");
    if (args.workflow && args.workflow !== "none" || args.includeContent === true) throw new Error("Amadeus uses foreground search without summaries or background fetching");
    return { ...args, workflow: "none", includeContent: false };
  }
  if (name === "source_check") {
    if (args.fetchContent === true) throw new Error("Use fetch_content to explicitly select public pages for reading");
    if (Array.isArray(args.queries) && args.queries.length > 4) throw new Error("Use at most four web search queries per call");
    return { ...args, fetchContent: false };
  }
  if (name === "fetch_content") {
    if (args.auth !== undefined || args.timestamp !== undefined || args.frames !== undefined || args.model !== undefined || args.answerModel !== undefined || args.forceClone !== undefined || args.proxy !== undefined || args.prompt !== undefined) {
      throw new Error("Amadeus web fetching supports public URLs; browser auth, cloning, video and model-answer options are unavailable");
    }
    if (args.mode !== undefined && !["readable", "raw"].includes(String(args.mode))) throw new Error("Use readable or raw web fetching");
    const urls = args.urls ?? (args.url === undefined ? [] : [args.url]);
    if (!Array.isArray(urls) || urls.length < 1 || urls.length > 5) throw new Error("Fetch one to five public HTTP(S) URLs");
    for (const value of urls) {
      if (typeof value !== "string") throw new Error("Expected a public HTTP(S) URL");
      let url: URL;
      try { url = new URL(value); } catch { throw new Error("Expected a public HTTP(S) URL"); }
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Expected a public HTTP(S) URL without credentials");
      const host = url.hostname.toLowerCase();
      if (host === "github.com" || host.endsWith(".github.com") || host === "raw.githubusercontent.com" || host === "gist.githubusercontent.com") throw new Error("Use inspect_repository and read_repository_file for pinned GitHub source access");
      if (/\.pdf$/i.test(url.pathname) || host === "arxiv.org" && url.pathname.startsWith("/pdf/")) throw new Error("Use download_arxiv or import_document for page-aware PDF evidence");
    }
  }
  return args;
}

function webParameters(tool: ToolDefinition): ToolDefinition["parameters"] {
  const schema = tool.parameters as ToolDefinition["parameters"] & { properties: Record<string, Record<string, unknown>> };
  const parameters = { ...schema, properties: { ...schema.properties } };
  const hide = tool.name === "web_search" ? ["workflow", "includeContent", "proxy"]
    : tool.name === "source_check" ? ["fetchContent", "proxy"]
    : tool.name === "fetch_content" ? ["auth", "forceClone", "timestamp", "frames", "model", "answerModel", "proxy", "prompt"] : [];
  for (const name of hide) delete parameters.properties[name];
  if (tool.name === "fetch_content" && parameters.properties.mode) {
    parameters.properties.mode = { ...parameters.properties.mode, enum: ["readable", "raw"] };
  }
  return parameters;
}

interface CapturedTool { tool: ToolDefinition; policy: PackagePolicy }
interface Lifecycle { event: "session_start" | "session_tree" | "session_shutdown"; handler: (...args: any[]) => unknown }
export interface PackageAdapter {
  policies: Record<string, PackagePolicy>;
  tools: CapturedTool[];
  register(): void;
}

/** Native package factories are reused; only explicitly selected tools are registered. */
export async function preparePackageTools(pi: ExtensionAPI, selection: PackageSelection, options: { offline: boolean; authorize: (policy: PackagePolicy, name: string, args: Record<string, unknown>, ctx: ExtensionContext) => Promise<boolean> }): Promise<PackageAdapter> {
  scopeFetch();
  const jiti = createJiti(import.meta.url, { interopDefault: true, alias: packageModuleAliases() });
  const captured = new Map<string, CapturedTool>();
  const lifecycle: Lifecycle[] = [];
  const selectedPolicies: Record<string, PackagePolicy> = Object.create(null);
  const bySource = new Map<string, SelectedPackageExtension[]>();
  for (const extension of selection.extensions) {
    const list = bySource.get(extension.source) ?? [];
    list.push(extension); bySource.set(extension.source, list);
  }
  for (const [source, extensions] of bySource) {
    const allowed = Object.fromEntries(Object.entries(selection.policies).filter(([, policy]) => policy.source === source && (!options.offline || !policy.network)));
    if (!Object.keys(allowed).length) continue;
    let loading = true;
    const proxy = new Proxy(pi, {
      get(target, key) {
        if (key === "registerTool") return (tool: ToolDefinition) => {
          if (!loading) throw new Error("Dynamic package tool registration is unavailable");
          if (reserved.has(tool.name) || tool.name.startsWith("mcp__")) throw new Error(`Package ${source} attempted to replace a reserved tool`);
          if (!Object.hasOwn(allowed, tool.name)) return;
          if (captured.has(tool.name)) throw new Error(`Duplicate package tool: ${tool.name}`);
          captured.set(tool.name, { tool, policy: allowed[tool.name] });
        };
        if (key === "on") return (event: string, handler: (...args: any[]) => unknown) => {
          // The audited web package needs cache/session cleanup, but never a second agent loop.
          if (source === "npm:pi-web-access@0.35.0" && ["session_start", "session_tree", "session_shutdown"].includes(event)) lifecycle.push({ event: event as Lifecycle["event"], handler });
          return () => {};
        };
        if (["registerCommand", "registerShortcut", "registerFlag", "registerProvider", "registerMcpServer", "unregisterMcpServer", "registerVirtualModel", "setActiveTools"].includes(String(key))) return () => {};
        if (key === "getFlag") return () => undefined;
        if (key === "exec" || key === "sendUserMessage") return () => { throw new Error("Use Amadeus's managed tools for execution and follow-up turns"); };
        if (key === "sendMessage") return (message: Parameters<ExtensionAPI["sendMessage"]>[0]) => target.sendMessage(message, { triggerTurn: false });
        const value = Reflect.get(target, key);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    for (const extension of extensions) {
      const factory = await jiti.import(extension.path, { default: true });
      if (typeof factory !== "function") throw new Error(`Package ${source} has no extension factory`);
      await factory(proxy);
    }
    loading = false;
    for (const [name, policy] of Object.entries(allowed)) {
      if (captured.get(name)?.policy.source !== source) throw new Error(`Package ${source} did not register the selected tool ${name}`);
      selectedPolicies[name] = policy;
    }
  }
  return {
    policies: selectedPolicies, tools: [...captured.values()],
    register() {
      for (const { tool, policy } of captured.values()) {
        const isWeb = policy.source === "npm:pi-web-access@0.35.0";
        pi.registerTool({
          ...tool,
          ...(isWeb ? { parameters: webParameters(tool) } : {}),
          ...(tool.name === "web_search" ? { description: "Search the web using pi-web-access. Returns source-linked results. Foreground retrieval only; use fetch_content to read a selected public page. Service charges are separate from model usage." } : {}),
          ...(tool.name === "fetch_content" ? { description: "Read up to five public web pages using pi-web-access. Use import_document/download_arxiv for PDF evidence and pinned repository tools for GitHub code." } : {}),
          exposure: "direct",
          annotations: { readOnlyHint: policy.effect === "read", openWorldHint: policy.network },
          prepareLoadout: undefined,
          async execute(callId, rawArgs, signal, onUpdate, ctx) {
            const args = packageToolArguments(policy.source, tool.name, rawArgs as Record<string, unknown>);
            // This also covers nested calls and protects a tool re-activated by a loader.
            if (options.offline && policy.network) throw new Error("Package network tools are disabled in offline mode");
            if (!await options.authorize(policy, tool.name, args, ctx)) throw new Error("Package tool permission denied");
            const timeout = AbortSignal.timeout(60_000);
            const scope = AbortSignal.any(signal ? [signal, timeout] : [timeout]);
            scope.throwIfAborted();
            scopeFetch();
            if (policy.network || policy.effect === "external") recordPackageUsage(ctx.cwd, { session_id: ctx.sessionManager.getSessionId(), source: policy.source, tool: tool.name });
            return requestScope.run(scope, async () => {
              const result = await tool.execute(callId, args, scope, onUpdate, ctx);
              if (scope.aborted) throw scope.reason;
              if (result.details && typeof result.details === "object" && "error" in result.details && result.details.error) throw new Error(String(result.details.error));
              return result;
            });
          },
        });
      }
      for (const { event, handler } of lifecycle) {
        const callback = async (event: unknown, ctx: ExtensionContext) => { await handler(event, ctx); };
        if (event === "session_start") pi.on(event, callback);
        else if (event === "session_tree") pi.on(event, callback);
        else pi.on("session_shutdown", callback);
      }
    },
  };
}

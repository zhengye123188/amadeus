import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { createJiti } from "jiti";
import { packageModuleAliases } from "../bin/packages.mjs";

export const SUBAGENT_ENGINE_VERSION = "0.74.0";
const executionSha256 = "c9faafe98657767293d1a595901c7430645b92ef45377651f6784a5fefb17604";

/** The host owns this session. Upstream cannot create SDK sessions or discover resources. */
export interface DelegatedChildSession {
  subscribe(listener: (event: Record<string, any>) => void): () => void;
  prompt(text: string): Promise<void>;
  steer(text: string): Promise<void>;
  followUp(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): Promise<void>;
  hasQueuedMessages?(): boolean;
  readonly messages: readonly any[];
  readonly sessionFile: string | undefined;
  readonly sessionId: string;
  readonly modelId: string | undefined;
  readonly contextWindow?: number;
  detached?: boolean;
  shutDown?: boolean;
}

/** This is descriptive input, not authorization to load hooks, extensions, storage, or env. */
export interface DelegatedChildLaunch {
  cwd: string;
  model?: string;
  tools?: string[];
  systemPrompt?: string;
  ambientExtensions: boolean;
  extensionPaths: string[];
  noSkills: boolean;
  noContextFiles: boolean;
  [key: string]: unknown;
}

export interface DelegatedChildSessionFactory {
  create(launch: DelegatedChildLaunch): Promise<DelegatedChildSession>;
  dispose(): Promise<void>;
}

export interface DelegatedChildControls {
  steer(text: string): Promise<void>;
  followUp(text: string): Promise<void>;
}

export interface DelegatedRunInput {
  role: string;
  task: string;
  systemPrompt: string;
  runId: string;
  cwd: string;
  model: string;
  tools: readonly string[];
  childSessionFactory: DelegatedChildSessionFactory;
  parentProviderRegistry?: unknown;
  parentSessionId?: string;
  signal?: AbortSignal;
  thinkingLevel?: "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
  timeoutMs: number;
  onSession?: (controls: DelegatedChildControls) => void;
  onUpdate?: (result: Record<string, any>) => void;
}

export interface DelegatedRunResult {
  index: number;
  agent: string;
  exitCode: number;
  finalOutput?: string;
  error?: string;
  timedOut?: boolean;
  stopped?: boolean;
  interrupted?: boolean;
  messages?: any[];
  usage: { input: number; output: number; cacheRead: number; cacheWrite: number; cost: number; turns: number };
  progressSummary?: { toolCount?: number; tokens?: number; durationMs?: number };
  truncation?: { text: string; truncated: boolean };
  [key: string]: unknown;
}

type RunSync = (cwd: string, agents: Record<string, unknown>[], role: string, task: string, options: Record<string, unknown>) => Promise<DelegatedRunResult>;
let engine: Promise<RunSync> | undefined;

/** Resolve through the package's exported root; fail closed on unaudited internal layouts. */
export function resolveSubagentEngineDirectory(): string {
  const entry = createRequire(import.meta.url).resolve("pi-subagents");
  const root = realpathSync(dirname(entry));
  const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  if (manifest.name !== "pi-subagents" || manifest.version !== SUBAGENT_ENGINE_VERSION) {
    throw new Error(`Amadeus requires audited pi-subagents@${SUBAGENT_ENGINE_VERSION}`);
  }
  const file = join(root, "src", "runs", "foreground", "execution.js");
  if (createHash("sha256").update(readFileSync(file)).digest("hex") !== executionSha256) {
    throw new Error("The pinned Pi subagent runner changed; re-audit its adapter before use");
  }
  return root;
}

/**
 * Reuse the pinned executor without its ambient refinement, watchdog, or Orca features.
 * Jiti virtual imports replace the host-policy seams in memory. Package
 * files remain intact; the public extension, workflows, resource discovery, and SDK
 * session factory are never invoked. An engine upgrade requires an explicit audit.
 */
export async function loadSubagentRunner(): Promise<RunSync> {
  if (!engine) engine = (async () => {
    const root = resolveSubagentEngineDirectory();
    const file = join(root, "src", "runs", "foreground", "execution.js");
    const childHooks = {
      createCapturedChildHooks: () => ({ hooks: [], toolDiagnostic: () => undefined,
        runtimeAcknowledgedExtensions: () => undefined, finalDrainHeld: () => false }),
      withChildSessionErrorReporting: (session: DelegatedChildLaunch) => session,
    };
    const jiti = createJiti(import.meta.url, {
      alias: packageModuleAliases(),
      tryNative: false,
      transformModules: ["pi-subagents"],
      moduleCache: false,
      virtualModules: {
        "../shared/effective-system-prompt.js": { buildEffectiveSystemPrompt: ({ agent }: { agent: { systemPrompt: string } }) => agent.systemPrompt },
        "../../watchdog/settings.js": { resolveWatchdogConfig: () => ({ ok: false }) },
        "../shared/orca-progress-tabs.js": { createOrcaProgressTab: () => undefined },
        "../../agents/skills.js": { resolveSkillsWithFallback: () => ({ resolved: [], missing: [] }) },
        "./child-hooks.js": childHooks,
        "../shared/child-session.js": {
          childSessionFactory: () => { throw new Error("Ambient child sessions are disabled"); },
          childSessionHasQueuedMessages: (session: DelegatedChildSession) => session.hasQueuedMessages?.() === true,
          projectChildSessionEventForJson: (event: unknown) => event,
        },
      },
    });
    // Async .js import can take Jiti's native ESM shortcut, which bypasses virtual
    // modules. The synchronous transformed loader is required for these seams.
    const module = jiti(file) as { runSync: RunSync };
    if (typeof module.runSync !== "function") throw new Error("The pinned Pi subagent executor is unavailable");
    return module.runSync;
  })().catch(error => { engine = undefined; throw error; });
  return engine;
}

/** Single interactive delegation; the calling host supplies roles, scheduling and permissions. */
export async function runDelegatedAgent(input: DelegatedRunInput): Promise<DelegatedRunResult> {
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(input.role)) throw new Error("Invalid delegated agent role");
  if (!input.model || !input.model.includes("/") || /[\0\r\n]/.test(input.model)) throw new Error("An inherited provider/model is required");
  if (!Number.isInteger(input.timeoutMs) || input.timeoutMs <= 0) throw new Error("A positive delegation timeout is required");
  if (!input.childSessionFactory || typeof input.childSessionFactory.create !== "function") throw new Error("A controlled child session factory is required");
  if (input.tools.some(tool => !/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(tool))) throw new Error("Invalid delegated tool name");
  input.signal?.throwIfAborted();
  const tools = [...new Set(input.tools)];
  const agent = {
    name: input.role, description: input.role, source: "runtime", filePath: "",
    systemPrompt: input.systemPrompt, systemPromptMode: "replace",
    inheritProjectContext: false, inheritGlobalContext: false, inheritSkills: false,
    allowNestedSubagents: false, maxSubagentDepth: 0, tools, skills: [],
    extensions: [], subagentOnlyExtensions: [], mutationTools: [],
    model: input.model,
  };
  const runSync = await loadSubagentRunner();
  try {
    const result = await runSync(input.cwd, [agent], input.role, input.task, {
    runId: input.runId, cwd: input.cwd, context: "fresh", projectTrusted: false,
    childSessionFactory: input.childSessionFactory,
    parentProviderRegistry: input.parentProviderRegistry, parentSessionId: input.parentSessionId,
    signal: input.signal, abortedAsStopped: true, timeoutMs: input.timeoutMs, toolTimeoutMs: Math.min(input.timeoutMs, 60_000),
    modelOverride: input.model, modelOverrideFromParent: true, modelOrigin: "inherited",
    thinkingOverride: input.thinkingLevel ?? "off",
    skills: [], requiredExtensions: [], maxSubagentDepth: 0,
    waitToolEnabled: false, allowIntercomDetach: false, share: false,
    artifactConfig: { enabled: false }, acceptance: { level: "none", reason: "Read-only analysis; the parent verifies returned findings" },
    capabilityCeiling: { version: 1, allowedTools: tools, allowedAgents: [input.role], denyExtensions: true, sources: ["research-cli"] },
    maxOutput: { bytes: 50_000, lines: 2_000 },
    onChildSession: input.onSession, onUpdate: input.onUpdate,
    });
    // Upstream preserves the full finalOutput and adds a separate truncation field.
    // Only the bounded view crosses this adapter; the host owns durable history.
    if (result.truncation?.truncated) result.finalOutput = result.truncation.text;
    return result;
  } finally {
    await input.childSessionFactory.dispose();
  }
}

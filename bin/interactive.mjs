/** Research's interactive host. Pi continues to own editing, sessions and agent execution. */
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const VALUE_FLAGS = new Set(["--provider", "--model", "--api-key", "--system-prompt", "--append-system-prompt", "--name", "-n", "--session", "--session-id", "--fork", "--session-dir", "--models", "--thinking", "--mode", "--extension", "-e", "--skill", "--prompt-template", "--theme", "--use-theme", "--tui-mode"]);

// Preserve Pi's print/JSON/RPC and utility paths. Values and text after -- are not flags.
export function shouldUseResearchTui(args, { stdinTTY = process.stdin.isTTY, stdoutTTY = process.stdout.isTTY } = {}) {
  if (!stdinTTY || !stdoutTTY) return false;
  if (["auth", "config", "mcp", "uninstall"].includes(args[0])) return false;
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === "--") break;
    if (["-p", "--print", "--export", "--list-models", "--help", "-h", "--version", "-v"].includes(arg)) return false;
    if (arg === "--mode" && ["json", "rpc"].includes(args[index + 1])) return false;
    if (VALUE_FLAGS.has(arg)) index++;
  }
  return true;
}

export function researchWindowTitle(title) {
  return String(title).replace(/^(?:π|pi)(?= - |$)/, "Research CLI").replace(/[\u0000-\u001f\u007f-\u009f]/g, " ");
}

/** Branding is host-owned, while all ordinary preferences retain Pi's storage. */
export function createResearchSettings(settings, piVersion) {
  const methods = new Map();
  let theme = settings.getThemeSetting();
  return new Proxy(settings, {
    get(target, property) {
      if (property === "getQuietStartup") return () => true;
      if (property === "getLastChangelogVersion") return () => piVersion;
      if (property === "getThemeSetting") return () => theme;
      if (property === "getTheme") return () => theme?.includes("/") ? undefined : theme;
      if (property === "getSettings") return () => ({ ...target.getSettings(), quietStartup: true, lastChangelogVersion: piVersion, theme });
      if (property === "applyOverrides") return overrides => {
        if (Object.hasOwn(overrides, "theme")) theme = overrides.theme;
        target.applyOverrides(overrides);
      };
      if (property === "setTheme") return name => { theme = name; target.setTheme(name); };
      const value = Reflect.get(target, property, target);
      if (typeof value !== "function") return value;
      // SettingsManager methods must run on their original instance: internal
      // saves/reloads are allowed to change preferences without exposing Pi's
      // welcome screen or changelog on the next interactive initialization.
      if (!methods.has(value)) methods.set(value, value.bind(target));
      return methods.get(value);
    },
  });
}

function expandPath(path, cwd) {
  const expanded = path === "~" ? homedir() : path.startsWith("~/") ? resolve(homedir(), path.slice(2)) : path;
  return isAbsolute(expanded) ? expanded : resolve(cwd, expanded);
}

function validateSessionFlags(parsed) {
  if (parsed.fork && (parsed.session || parsed.continue || parsed.resume || parsed.noSession)) {
    throw new Error("--fork cannot be combined with --session, --continue, --resume or --no-session");
  }
  if (parsed.sessionId !== undefined) {
    if (parsed.session || parsed.continue || parsed.resume) throw new Error("--session-id cannot be combined with --session, --continue or --resume");
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/.test(parsed.sessionId)) throw new Error("Invalid --session-id: use letters, numbers, dots, underscores or hyphens, with a letter or number at both ends");
  }
  if (parsed.name !== undefined && !parsed.name.trim()) throw new Error("--name requires a non-empty value");
}

async function findSessionPath(reference, cwd, sessionDir, SessionManager) {
  if (reference.includes("/") || reference.includes("\\") || reference.endsWith(".jsonl")) return { path: expandPath(reference, cwd) };
  const exact = SessionManager.findById(cwd, reference, sessionDir);
  if (exact) return { path: exact };
  const local = await SessionManager.list(cwd, sessionDir);
  const localMatch = local.find(session => session.id.startsWith(reference));
  if (localMatch) return { path: localMatch.path };
  const global = await SessionManager.listAll(sessionDir);
  const globalMatch = global.find(session => session.id === reference) ?? global.find(session => session.id.startsWith(reference));
  if (globalMatch) return { path: globalMatch.path, global: true, cwd: globalMatch.cwd };
  throw new Error(`No session found matching '${reference}'`);
}

export async function createInteractiveSession(parsed, cwd, sessionDir, SessionManager, resolvedSession) {
  validateSessionFlags(parsed);
  if (parsed.noSession) return SessionManager.inMemory(cwd, parsed.sessionId ? { id: parsed.sessionId } : undefined);
  if (parsed.fork) {
    if (parsed.sessionId && SessionManager.findById(cwd, parsed.sessionId, sessionDir)) throw new Error(`Session already exists with id '${parsed.sessionId}'`);
    return SessionManager.forkFrom((await findSessionPath(parsed.fork, cwd, sessionDir, SessionManager)).path, cwd, sessionDir, { id: parsed.sessionId });
  }
  if (parsed.session) {
    const selected = resolvedSession ?? await findSessionPath(parsed.session, cwd, sessionDir, SessionManager);
    // A global ID requires a confirmation/fork after the trusted core has initialized.
    if (selected.global) return SessionManager.inMemory(cwd);
    return SessionManager.open(selected.path, sessionDir);
  }
  if (parsed.resume) return SessionManager.inMemory(cwd);
  if (parsed.continue) return SessionManager.continueRecent(cwd, sessionDir);
  if (parsed.sessionId) {
    const existing = SessionManager.findById(cwd, parsed.sessionId, sessionDir);
    if (existing) return SessionManager.open(existing, sessionDir);
  }
  return SessionManager.create(cwd, sessionDir, { id: parsed.sessionId });
}

async function selectSession(cwd, sessionDir, runtime, terminal, sdk, tui) {
  const settings = runtime.services.settingsManager;
  // The public InteractiveMode constructor installs the complete application/user
  // keymap. It does not paint until init/run, so no upstream welcome is displayed.
  const keymapHost = new sdk.InteractiveMode(runtime, { terminal });
  const ui = new tui.TuiMainScreen(terminal, settings.getShowHardwareCursor(), sdk.getAgentDir());
  try { return await new Promise(resolveSelection => {
    let settled = false;
    const finish = path => {
      if (settled) return;
      settled = true;
      ui.stop();
      resolveSelection(path);
    };
    const selector = new sdk.SessionSelectorComponent(
      (onProgress, signal) => sdk.SessionManager.list(cwd, sessionDir, onProgress, signal),
      (onProgress, signal) => sdk.SessionManager.listAll(sessionDir, onProgress, signal),
      finish, () => finish(undefined), () => finish(undefined), () => ui.requestRender(),
      { showRenameHint: false, keybindings: tui.getKeybindings() },
    );
    ui.addChild(new tui.Text("Research CLI · 恢复会话", 1, 1));
    ui.addChild(selector);
    ui.setFocus(selector.getSessionList());
    ui.start();
  }); } finally {
    keymapHost.stop();
    runtime.setBeforeSessionInvalidate(undefined);
    runtime.setRebindSession(undefined);
  }
}

async function prepareInitialMessage(parsed, cwd, settings, sdk) {
  const parts = [], images = [];
  for (const file of parsed.fileArgs) {
    const path = expandPath(file, cwd);
    const bytes = await readFile(path);
    if (!bytes.length) continue;
    const name = path.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    const mimeType = await sdk.detectSupportedImageMimeTypeFromFile(path);
    if (mimeType) {
      if (settings.getImageAutoResize()) {
        const resized = await sdk.resizeImage(bytes, mimeType);
        if (!resized) throw new Error(`Could not prepare image attachment: ${path}`);
        images.push({ type: "image", mimeType: resized.mimeType, data: resized.data });
        parts.push(`<file name="${name}">${sdk.formatDimensionNote(resized) ?? ""}</file>\n`);
      } else {
        images.push({ type: "image", mimeType, data: bytes.toString("base64") });
        parts.push(`<file name="${name}"></file>\n`);
      }
    } else parts.push(`<file name="${name}">\n${bytes.toString("utf8").replace(/^\ufeff/, "")}\n</file>\n`);
  }
  if (parsed.messages.length) parts.push(parsed.messages.shift());
  return { initialMessage: parts.length ? parts.join("") : undefined, initialImages: images.length ? images : undefined };
}

/** Public SDK only: resource isolation is identical to the managed Pi CLI flags. */
export async function runResearchInteractive(args) {
  // Research releases are managed separately; do not advertise upstream Pi upgrades.
  process.env.PI_SKIP_VERSION_CHECK ??= "1";
  const sdk = await import("@earendil-works/pi-coding-agent");
  // Pi's shrinkwrap can install a separate physical TUI copy, even at the same
  // version. Resolve its public dependency from Pi so keymaps/capabilities agree.
  const piRequire = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
  const tui = await import(pathToFileURL(piRequire.resolve("@earendil-works/pi-tui")).href);
  const parsed = sdk.parseArgs(args);
  const parseErrors = parsed.diagnostics.filter(diagnostic => diagnostic.type === "error");
  if (parseErrors.length) throw new Error(parseErrors.map(diagnostic => diagnostic.message).join("\n"));
  validateSessionFlags(parsed);
  const originalCwd = process.cwd(), agentDir = sdk.getAgentDir();
  const checkout = fileURLToPath(new URL("../", import.meta.url));
  const pathList = paths => paths?.map(path => expandPath(path, originalCwd));
  const startupSettings = sdk.SettingsManager.create(originalCwd, agentDir, { projectTrusted: false });
  const originalTheme = parsed.useTheme ?? startupSettings.getThemeSetting() ?? "system";
  // Automatic light/dark settings and old Research themes fall back to terminal
  // colors for /ui system; a specific explicit theme remains available by name.
  process.env.RESEARCH_UI_BASE_THEME = originalTheme.includes("/") || originalTheme.startsWith("research-") ? "system" : originalTheme;
  if (parsed.useTheme !== undefined) process.env.RESEARCH_UI_THEME = "system";
  const sessionDirValue = parsed.sessionDir ?? process.env.PI_CODING_AGENT_SESSION_DIR ?? startupSettings.getSessionDir();
  const sessionDir = sessionDirValue ? expandPath(sessionDirValue, originalCwd) : undefined;
  const resolvedSession = parsed.session && !parsed.noSession ? await findSessionPath(parsed.session, originalCwd, sessionDir, sdk.SessionManager) : undefined;
  const wantsResume = parsed.resume && !parsed.noSession && !parsed.session;
  const sessionManager = await createInteractiveSession(parsed, originalCwd, sessionDir, sdk.SessionManager, resolvedSession);
  if (!wantsResume && !resolvedSession?.global && parsed.name !== undefined) sessionManager.appendSessionInfo(parsed.name.trim());

  const createRuntime = async ({ cwd, agentDir, sessionManager, sessionStartEvent }) => {
    // Ambient project settings stay untrusted, as do resource discovery and builtin tools.
    const settings = createResearchSettings(sdk.SettingsManager.create(cwd, agentDir, { projectTrusted: false }), sdk.VERSION);
    const monochrome = process.env.NO_COLOR !== undefined || process.env.TERM === "dumb";
    const theme = monochrome ? "research-mono" : process.env.RESEARCH_UI_THEME === "system"
      ? process.env.RESEARCH_UI_BASE_THEME : "research-pixel";
    settings.applyOverrides({ quietStartup: true, lastChangelogVersion: sdk.VERSION, theme });
    const services = await sdk.createAgentSessionServices({
      cwd, agentDir, settingsManager: settings, modelRuntimeSignal: AbortSignal.timeout(15_000), extensionFlagValues: parsed.unknownFlags,
      resourceLoaderOptions: {
        additionalExtensionPaths: pathList(parsed.extensions), additionalSkillPaths: pathList(parsed.skills),
        additionalPromptTemplatePaths: pathList(parsed.promptTemplates),
        additionalThemePaths: [resolve(checkout, "pi/themes/research-pixel.json"), resolve(checkout, "pi/themes/research-mono.json"), ...(pathList(parsed.themes) ?? [])],
        noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
        systemPrompt: parsed.systemPrompt, appendSystemPrompt: parsed.appendSystemPrompt,
      },
    });
    const diagnostics = [...services.diagnostics, ...parsed.diagnostics,
      ...settings.drainErrors().map(({ error }) => ({ type: "warning", message: `Research settings: ${error.message}` })),
      ...services.resourceLoader.getExtensions().errors.map(({ path, error }) => ({ type: "error", message: `Failed to load extension "${path}": ${error}` })),
    ];
    if (parsed.verbose) diagnostics.push({ type: "info", message: "Research CLI shows startup diagnostics while retaining the Research welcome screen." });
    let model, thinkingLevel = parsed.thinking;
    if (parsed.model) {
      const resolved = sdk.resolveCliModel({ cliProvider: parsed.provider, cliModel: parsed.model, cliThinking: parsed.thinking, modelRuntime: services.modelRuntime });
      if (resolved.error) diagnostics.push({ type: "error", message: resolved.error });
      if (resolved.warning) diagnostics.push({ type: "warning", message: resolved.warning });
      model = resolved.model;
      thinkingLevel ??= resolved.thinkingLevel;
    }
    const patterns = parsed.models ?? settings.getEnabledModels();
    const { scopedModels, diagnostics: scopeDiagnostics } = patterns?.length
      ? await sdk.resolveModelScopeWithDiagnostics(patterns, services.modelRuntime, { signal: AbortSignal.timeout(15_000) })
      : { scopedModels: [], diagnostics: [] };
    diagnostics.push(...scopeDiagnostics);
    if (!model && scopedModels.length && !sessionManager.buildSessionContext().messages.length) {
      const saved = scopedModels.find(({ model }) => model.provider === settings.getDefaultProvider() && model.id === settings.getDefaultModel()) ?? scopedModels[0];
      model = saved.model;
      thinkingLevel ??= saved.thinkingLevel;
    }
    if (parsed.apiKey) {
      if (!model) diagnostics.push({ type: "error", message: "--api-key requires an explicit --model or --models selection" });
      else await services.modelRuntime.setRuntimeApiKey(model.provider, parsed.apiKey);
    }
    if (diagnostics.some(diagnostic => diagnostic.type === "error")) throw new Error(diagnostics.filter(diagnostic => diagnostic.type === "error").map(diagnostic => diagnostic.message).join("\n"));
    const created = await sdk.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model, thinkingLevel, scopedModels, noTools: "builtin" });
    return { ...created, services, diagnostics };
  };
  let runtime = await sdk.createAgentSessionRuntime(createRuntime, { cwd: sessionManager.getCwd(), agentDir, sessionManager });
  class ResearchTerminal extends tui.ProcessTerminal {
    setTitle(title) { super.setTitle(researchWindowTitle(title)); }
  }
  const terminal = new ResearchTerminal();
  let mode;
  try {
    // InteractiveMode registers the explicitly selected themes before applying
    // the saved choice; the initial color query starts from the system palette.
    sdk.initTheme("system", true);
    if (wantsResume || resolvedSession?.global) {
      let selected;
      if (wantsResume) {
        const path = await selectSession(originalCwd, sessionDir, runtime, terminal, sdk, tui);
        if (!path) return;
        selected = sdk.SessionManager.open(path, sessionDir);
      } else {
        const readline = createInterface({ input: process.stdin, output: process.stdout });
        let answer;
        try {
          const source = String(resolvedSession.cwd ?? "another project").replace(/[\u0000-\u001f\u007f-\u009f]/g, " ");
          answer = await readline.question(`Session found in different project: ${source}\nFork this session into the current workspace? [y/N] `);
        } finally { readline.close(); }
        if (!["y", "yes"].includes(answer.trim().toLowerCase())) return;
        selected = sdk.SessionManager.forkFrom(resolvedSession.path, originalCwd, sessionDir);
      }
      // The bootstrap session had no TUI/tool access. Recreate in the chosen cwd,
      // retaining the explicitly selected session directory and restored model.
      await runtime.dispose();
      runtime = await sdk.createAgentSessionRuntime(createRuntime, { cwd: selected.getCwd(), agentDir, sessionManager: selected });
      if (parsed.name !== undefined) selected.appendSessionInfo(parsed.name.trim());
    }
    const initial = await prepareInitialMessage(parsed, originalCwd, runtime.services.settingsManager, sdk);
    mode = new sdk.InteractiveMode(runtime, {
      terminal, startupDiagnostics: runtime.diagnostics, modelFallbackMessage: runtime.modelFallbackMessage,
      ...initial, initialMessages: parsed.messages, verbose: false, tuiMode: parsed.tuiMode,
    });
    await mode.run();
  } finally {
    mode?.stop();
    await runtime.dispose();
    terminal.stop();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await runResearchInteractive(process.argv.slice(2)); }
  catch (error) { console.error(`Research CLI could not start: ${error.message}`); process.exitCode = 2; }
}

import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { createJiti } from "jiti";
import { DefaultPackageManager, SettingsManager } from "@earendil-works/pi-coding-agent";

/** Resolve ESM-only Pi modules before the TypeScript extension loader is involved. */
export function packageModuleAliases() {
  const aliases = {};
  const resolver = createJiti(import.meta.resolve("@earendil-works/pi-coding-agent"));
  for (const [short, specifier] of [["pi-coding-agent", "@earendil-works/pi-coding-agent"], ["pi-agent-core", "@earendil-works/pi-agent-core"], ["pi-tui", "@earendil-works/pi-tui"], ["pi-ai", "@earendil-works/pi-ai/compat"]]) {
    const path = fileURLToPath(resolver.esmResolve(specifier));
    aliases[`@earendil-works/${short}`] = path;
    aliases[`@mariozechner/${short}`] = path;
  }
  for (const name of ["typebox", "typebox/value", "typebox/compile"]) {
    const path = fileURLToPath(resolver.esmResolve(name));
    aliases[name] = path;
    aliases[name.replace("typebox", "@sinclair/typebox")] = path;
  }
  return aliases;
}

const effectNames = new Set(["read", "write", "execute", "external"]);
const reservedTools = new Set(["read", "write", "edit", "bash", "powershell", "grep", "find", "ls", "codemode", "tool_search", "__proto__", "constructor", "prototype"]);
const npmSource = /^npm:((?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*)@((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$/;

/** Audited versions bundled as application dependencies, never installed at startup. */
export const builtinPackages = [
  { source: "npm:pi-docparser@4.0.0", name: "pi-docparser", version: "4.0.0", role: "parser-engine", extensions: [], effects: {}, networkTools: [] },
  { source: "npm:pi-web-access@0.35.0", name: "pi-web-access", version: "0.35.0", role: "tools", extensions: ["dist/index.js"], effects: { web_search: "external", source_check: "external", fetch_content: "external", get_search_content: "read" }, networkTools: ["web_search", "source_check", "fetch_content"] },
  { source: "npm:@upstash/context7-pi@0.1.2", name: "@upstash/context7-pi", version: "0.1.2", role: "tools", extensions: ["extensions/context7.ts"], effects: { "resolve-library-id": "read", "query-docs": "read" }, networkTools: ["resolve-library-id", "query-docs"] },
];

function object(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function inside(root, path) { const part = relative(root, path); return part !== ".." && !part.startsWith(".." + sep) && !isAbsolute(part); }

export function packagePaths(env = process.env) {
  return {
    configFile: join(env.XDG_CONFIG_HOME || join(homedir(), ".config"), "research-cli", "packages.json"),
    agentDir: join(env.XDG_DATA_HOME || join(homedir(), ".local", "share"), "research-cli", "pi-packages"),
  };
}

/** Only exact npm versions, complete Git commits and explicitly selected local directories. */
export function normalizePackageSource(source, cwd = process.cwd(), requireLocal = false) {
  if (typeof source !== "string" || !source || source !== source.trim() || /[\0\r\n]/.test(source)) throw new Error("Invalid package source");
  if (npmSource.test(source)) {
    const version = npmSource.exec(source)[2];
    const prerelease = version.split("+")[0].split("-").slice(1).join("-");
    const identifiers = [...(prerelease ? prerelease.split(".") : []), ...(version.includes("+") ? version.split("+")[1].split(".") : [])];
    if (identifiers.some(value => !value || !/^[0-9A-Za-z-]+$/.test(value)) || prerelease.split(".").some(value => /^0\d+$/.test(value))) throw new Error("npm packages require a valid exact semantic version");
    return source;
  }
  if (source.startsWith("npm:")) throw new Error("npm packages require an exact version, for example npm:package@1.2.3");
  if (source.startsWith("git:")) {
    const match = /^(git:https:\/\/[^@]+)@([a-fA-F0-9]{40})$/.exec(source);
    if (!match) throw new Error("Git packages require an HTTPS repository and complete 40-character commit");
    let url;
    try { url = new URL(match[1].slice(4)); } catch { throw new Error("Invalid Git package source"); }
    const parts = url.pathname.slice(1).split("/");
    if (url.username || url.password || url.search || url.hash || parts.length < 2 || parts.some(part => !/^[\w.-]+$/.test(part) || part === "." || part === "..")) throw new Error("Invalid Git package repository");
    return match[1] + "@" + match[2].toLowerCase();
  }
  if (!(isAbsolute(source) || source === "." || source === ".." || source.startsWith("./") || source.startsWith("../"))) throw new Error("Local packages require an explicit directory path, for example ./my-extension");
  const path = resolve(cwd, source);
  if (!requireLocal && !existsSync(path)) return path;
  try { if (!statSync(path).isDirectory()) throw new Error(); return realpathSync(path); }
  catch { throw new Error("Local package directory does not exist"); }
}

function identity(source) {
  const npm = npmSource.exec(source);
  if (npm) return "npm:" + npm[1];
  if (source.startsWith("git:")) return source.slice(0, source.lastIndexOf("@")).replace(/\.git$/, "");
  return source;
}

function resourcePaths(values, name) {
  if (values === undefined) return [];
  if (!Array.isArray(values) || values.length > 50 || values.some(value => typeof value !== "string" || !value || isAbsolute(value) || value.includes("\\") || /[\0\r\n*?!]/.test(value) || value.split("/").some(part => ["", ".", ".."].includes(part)))) throw new Error(`${name} requires exact package-relative paths without patterns`);
  if (new Set(values).size !== values.length) throw new Error(`Duplicate ${name} resource`);
  return values;
}

function policy(value) {
  if (!object(value) || Object.keys(value).some(key => !["extensions", "skills", "effects", "networkTools"].includes(key))) throw new Error("Package policy supports only extensions, skills, effects and networkTools");
  const extensions = resourcePaths(value.extensions, "extensions"), skills = resourcePaths(value.skills, "skills");
  const effects = value.effects ?? {};
  if (!object(effects) || Object.keys(effects).length > 64) throw new Error("Package effects must be an exact tool allowlist");
  for (const [name, effect] of Object.entries(effects)) {
    if (!/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(name) || reservedTools.has(name) || name.startsWith("mcp__") || !effectNames.has(effect)) throw new Error("Invalid or reserved package tool permission");
  }
  if (Object.keys(effects).length && !extensions.length) throw new Error("Enabled package tools require explicitly selected extension files");
  if (extensions.length && !Object.keys(effects).length) throw new Error("Extension files require an exact effects allowlist");
  const networkTools = value.networkTools ?? Object.keys(effects);
  if (!Array.isArray(networkTools) || networkTools.length > 64 || new Set(networkTools).size !== networkTools.length || networkTools.some(name => typeof name !== "string" || !Object.hasOwn(effects, name))) throw new Error("networkTools must list exact allowlisted tool names");
  return { extensions, skills, effects: { ...effects }, networkTools };
}

function readJson(file, description) {
  try {
    const info = lstatSync(file);
    if (!info.isFile() || info.isSymbolicLink() || info.size > 262144) throw new Error();
    return JSON.parse(readFileSync(file, "utf8"));
  } catch { throw new Error(`Invalid ${description} file`); }
}

export function readPackageManifest(file, cwd = process.cwd(), optional = false) {
  if (optional && !existsSync(file)) return { version: 1, packages: [] };
  const document = readJson(file, "package configuration");
  if (!object(document) || document.version !== 1 || !Array.isArray(document.packages) || document.packages.length > 16 || Object.keys(document).some(key => !["version", "packages"].includes(key))) throw new Error("Package configuration requires version 1 and a packages array (at most 16)");
  const seen = new Set();
  const packages = document.packages.map(entry => {
    if (!object(entry) || Object.keys(entry).some(key => !["source", "enabled", "extensions", "skills", "effects", "networkTools"].includes(key)) || entry.enabled !== undefined && typeof entry.enabled !== "boolean") throw new Error("Invalid package configuration entry");
    const source = normalizePackageSource(entry.source, cwd);
    const key = identity(source);
    if (seen.has(key) || builtinPackages.some(item => identity(item.source) === key)) throw new Error("Duplicate or bundled package source");
    seen.add(key);
    const clean = policy(Object.fromEntries(["extensions", "skills", "effects", "networkTools"].filter(key => key in entry).map(key => [key, entry[key]])));
    return { source, enabled: entry.enabled ?? Boolean(clean.extensions.length || clean.skills.length), ...clean };
  });
  return { version: 1, packages };
}

function saveManifest(file, document) {
  mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${randomUUID()}.tmp`;
  try { writeFileSync(temporary, JSON.stringify(document, null, 2) + "\n", { flag: "wx", mode: 0o600 }); renameSync(temporary, file); }
  finally { rmSync(temporary, { force: true }); }
}

function packageManager({ cwd, agentDir, entries = [], env }) {
  const bundledNpm = env.RESEARCH_BUNDLE_ROOT && join(env.RESEARCH_BUNDLE_ROOT, "runtime", "node", "bin", "npm");
  const npm = bundledNpm && existsSync(bundledNpm) ? bundledNpm : "npm";
  // In-memory settings prevent reads or writes of ambient .pi configuration. The manifest
  // persists only user-authorized sources; Pi owns installation and manifest resolution.
  const settings = SettingsManager.inMemory({ packages: entries.map(entry => entry.source), npmCommand: [npm, "--ignore-scripts"] }, { projectTrusted: false });
  return new DefaultPackageManager({ cwd, agentDir, settingsManager: settings });
}

function checkedPackageRoot(path, source, agentDir) {
  if (!path || !existsSync(path)) return undefined;
  const directory = realpathSync(path);
  const managedRoot = existsSync(agentDir) ? realpathSync(agentDir) : resolve(agentDir);
  if (!isAbsolute(source) && !inside(managedRoot, directory)) return undefined;
  const match = npmSource.exec(source);
  if (match) {
    try {
      const metadata = JSON.parse(readFileSync(join(directory, "package.json"), "utf8"));
      if (metadata.name !== match[1] || metadata.version !== match[2]) return undefined;
    } catch { return undefined; }
  }
  if (source.startsWith("git:")) {
    const expected = source.slice(source.lastIndexOf("@") + 1);
    const checked = spawnSync("git", ["rev-parse", "HEAD"], { cwd: directory, encoding: "utf8", timeout: 10000 });
    if (checked.error || checked.status !== 0 || checked.stdout.trim() !== expected) return undefined;
  }
  return directory;
}

function bundledDirectory(root, name) {
  // npm can hoist dependencies above a scoped application directory.
  const require = createRequire(join(root, "package.json"));
  return realpathSync(dirname(require.resolve(`${name}/package.json`)));
}

function builtinStatus(root) {
  return builtinPackages.map(item => {
    let path;
    let available = false;
    try { path = bundledDirectory(root, item.name); const metadata = JSON.parse(readFileSync(join(path, "package.json"), "utf8")); available = metadata.name === item.name && metadata.version === item.version; } catch { /* list also works before dependencies are installed */ }
    return { source: item.source, status: available ? item.role === "parser-engine" ? "parser-engine" : "bundled-enabled" : "bundled-missing", tools: Object.keys(item.effects), path: available ? realpathSync(path) : null };
  });
}

function exactResource(directory, name, file = false) {
  const path = resolve(directory, name);
  let resolved;
  try { resolved = realpathSync(path); if (!inside(directory, resolved) || file && !statSync(resolved).isFile()) throw new Error(); }
  catch { throw new Error(`Selected package resource is missing or outside its package: ${name}`); }
  return resolved;
}

/** Resolve only already installed, selected resources. Never fetch missing packages. */
export async function loadPackageSelection({ file, cwd = process.cwd(), root, env = process.env, includeBuiltin = true }) {
  const paths = packagePaths(env), configFile = file ? resolve(cwd, file) : paths.configFile;
  const document = readPackageManifest(configFile, file ? dirname(configFile) : cwd, !file);
  const manager = packageManager({ cwd, agentDir: paths.agentDir, entries: document.packages, env });
  const selection = { extensions: [], skills: [], policies: Object.create(null), disabledResearchTools: [], agentDir: paths.agentDir, configFile };
  const selected = [];
  if (includeBuiltin) {
    for (const entry of builtinPackages) {
      let directory;
      try { directory = bundledDirectory(root, entry.name); }
      catch { throw new Error(`Bundled package ${entry.source} is missing. Reinstall Research CLI.`); }
      const metadata = readJson(join(directory, "package.json"), "bundled package metadata");
      if (metadata.name !== entry.name || metadata.version !== entry.version) throw new Error(`Bundled package ${entry.source} is missing or has the wrong version. Reinstall Research CLI.`);
      if (entry.extensions.length) selected.push({ ...entry, skills: [], directory: realpathSync(directory) });
    }
  }
  for (const entry of document.packages.filter(entry => entry.enabled)) {
    const directory = checkedPackageRoot(manager.getInstalledPath(entry.source, "user"), entry.source, paths.agentDir);
    if (!directory) throw new Error(`Package ${entry.source} is not installed at the selected version. Run research packages install ${entry.source}.`);
    selected.push({ ...entry, directory });
  }
  for (const entry of selected) {
    // Resolve an already checked local directory using Pi's public resolver, then select
    // exact manifest-declared files. No npm/git source is passed into startup resolution.
    const resolved = await manager.resolveExtensionSources([entry.directory]);
    const available = new Set(resolved.extensions.filter(resource => resource.enabled).map(resource => realpathSync(resource.path)));
    for (const name of entry.extensions) {
      const path = exactResource(entry.directory, name, true);
      if (!available.has(path)) throw new Error(`Extension ${name} is not declared by package ${entry.source}`);
      selection.extensions.push({ path, source: entry.source, effects: entry.effects, networkTools: entry.networkTools });
    }
    for (const name of entry.skills) selection.skills.push(exactResource(entry.directory, name));
    for (const [name, effect] of Object.entries(entry.effects)) {
      if (name in selection.policies) throw new Error(`Duplicate package tool: ${name}`);
      selection.policies[name] = { effect, source: entry.source, network: entry.networkTools.includes(name) };
    }
  }
  return selection;
}

/** Return undefined for another CLI command, otherwise a process exit code. */
export async function handlePackageCommand(args, { cwd = process.cwd(), root, env = process.env, output = console.log } = {}) {
  if (args[0] !== "packages") return undefined;
  if (args.includes("--help") || args.includes("-h")) {
    output("research packages list\nresearch packages install SOURCE [--policy FILE]\nresearch packages remove SOURCE\n\nUse npm:package@exact-version, git:https://host/owner/repo@full-commit, or ./local-directory.\nPolicy JSON: {\"extensions\":[\"extension.ts\"],\"effects\":{\"tool_name\":\"read\"}}.\nPackages without a policy are installed but disabled. Installation skips lifecycle scripts.\nBundled packages are managed with the Research CLI version.");
    return 0;
  }
  const action = args[1], paths = packagePaths(env);
  if (!["install", "remove", "list"].includes(action)) throw new Error("Usage: research packages install|list|remove");
  const document = readPackageManifest(paths.configFile, cwd, true);
  const manager = packageManager({ cwd, agentDir: paths.agentDir, entries: document.packages, env });
  if (action === "list") {
    if (args.length !== 2) throw new Error("Usage: research packages list");
    const installed = manager.listConfiguredPackages();
    const users = document.packages.map(entry => {
      const found = installed.find(item => identity(normalizePackageSource(item.source, cwd)) === identity(entry.source));
      const path = checkedPackageRoot(found?.installedPath, entry.source, paths.agentDir);
      return { source: entry.source, status: path ? entry.enabled ? "installed-enabled" : "installed-disabled" : "missing", tools: Object.keys(entry.effects), path: path || null };
    });
    output(JSON.stringify({ bundled: builtinStatus(root), user: users }, null, 2));
    return 0;
  }
  if (!args[2] || args[2].startsWith("--")) throw new Error(`Usage: research packages ${action} SOURCE${action === "install" ? " [--policy FILE]" : ""}`);
  const source = normalizePackageSource(args[2], cwd, action === "install");
  if (builtinPackages.some(entry => identity(entry.source) === identity(source))) throw new Error("Bundled packages are managed with the Research CLI version; update or reinstall Research CLI");
  if (action === "remove") {
    if (args.length !== 3) throw new Error("Usage: research packages remove SOURCE");
    if (!document.packages.some(entry => identity(entry.source) === identity(source))) throw new Error("Package is not in the Research CLI manifest");
    await manager.removeAndPersist(source);
    saveManifest(paths.configFile, { version: 1, packages: document.packages.filter(entry => identity(entry.source) !== identity(source)) });
    output(`Removed ${source}. Local source directories are preserved.`);
    return 0;
  }
  let clean;
  if (args.length === 5 && args[3] === "--policy" && args[4] && !args[4].startsWith("--")) clean = policy(readJson(resolve(cwd, args[4]), "package policy"));
  else if (args.length !== 3) throw new Error("Usage: research packages install SOURCE [--policy FILE]");
  const old = document.packages.find(entry => entry.source === source);
  const entry = clean ? { source, enabled: Boolean(clean.extensions.length || clean.skills.length), ...clean } : old || { source, enabled: false, extensions: [], skills: [], effects: {} };
  await manager.installAndPersist(source);
  const packages = document.packages.filter(item => identity(item.source) !== identity(source));
  packages.push(entry);
  saveManifest(paths.configFile, { version: 1, packages });
  output(`Installed ${source}; ${entry.enabled ? "enabled with the selected policy" : "disabled until installed with --policy FILE"}. Restart Research CLI to apply changes.`);
  return 0;
}

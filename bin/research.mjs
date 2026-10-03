#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, lstatSync, mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { configPath, configure, loadApiConfig } from "./api-config.mjs";
import { checkApi } from "./api-doctor.mjs";
import { loadModelProfile } from "./model-profile.mjs";
import { handlePackageCommand, loadPackageSelection, packagePaths } from "./packages.mjs";
import { handleOcrCommand } from "./ocr.mjs";
import { shouldUseResearchTui } from "./interactive.mjs";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const args = process.argv.slice(2);
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 19)) {
  console.error("Amadeus needs Node >=22.19.0. Activate a supported Node version first.");
  process.exit(2);
}
// Package management is independent of model credentials and the Python backend.
try {
  const result = await handlePackageCommand(args, { cwd: process.cwd(), root, env: process.env });
  if (result !== undefined) process.exit(result);
  const ocr = await handleOcrCommand(args, { env: process.env });
  if (ocr !== undefined) process.exit(ocr);
} catch (error) { console.error(error.message); process.exit(2); }
if (args.includes("--version") || args[0] === "version") {
  console.log(`${pkg.version} (Pi ${pkg.dependencies["@earendil-works/pi-coding-agent"]})`);
  process.exit(0);
}
if (args.includes("--help") || args.includes("-h")) {
  console.log(`Amadeus ${pkg.version} — interactive research on Pi

research setup [--jev]                 Install the Python backend using uv
research configure                    Save API settings locally (hidden key input)
research doctor [--check-api]           Check runtimes; optionally GET /models (no generation)
research project backup|restore|info   Manage project archives and metadata
research packages list                Show bundled and explicitly installed Pi packages
research packages install SOURCE [--policy FILE]   Install a pinned package
research packages remove SOURCE       Remove a selected package
research ocr install [--languages eng,chi_sim,chi_tra]   Install local OCR language data
research ocr list                     Check local OCR models without network access
research [options]                     Open the interactive terminal
research [options] -p "question"        Run a noninteractive prompt

Research options:
  --workspace DIR                      Existing project directory (default: cwd)
  --permission ask|read-only|workspace-write   Default: ask
  --execution disabled|docker|local     Default: disabled; local is unsandboxed
  --approve-experiments                 Explicitly allow experiment calls without dialogs
  --offline                            Disable backend network tools (model may still use network)
  --memory on|off                       Project context/compaction ablation (default: on)
  --ui-avatar pixel|off                 Pixel character portrait (default: pixel)
  --ui-theme pixel|system               Interactive colors (default: pixel)
  --config FILE                        Python backend TOML configuration
  --model-profile FILE                 Explicit model capability/pricing JSON
  --mcp-config FILE                    Trusted external MCP JSON with per-tool allowlist
  --package-config FILE                Explicit Pi package selection and tool policies
  --instructions FILE                  Explicitly selected project instructions (e.g. AGENTS.md)
  --skill PATH                         Explicit Pi skill file or directory
  --max-turns N                        Model-step limit per prompt (default: 32)
  --max-seconds N                      Time budget per agent run (default: 600)
  --max-tokens N                       Soft token budget per prompt (default: 60000)
  --max-cost-usd N                     Soft model cost budget; requires configured prices

Pi options pass through: --provider, --model, -p, --mode json, --continue, --resume.
Set provider keys in environment or use /login. OPENAI_BASE_URL + RESEARCH_MODEL
select an OpenAI-compatible endpoint; RESEARCH_API=chat|responses selects protocol.
Interactive commands: /ui /agents /agents roles /memory /evidence /jobs /usage /review-memory /research-status /packages /mcp /compact /tree.
For full upstream options: research --pi-help
Python prototype: research-legacy (separate command).
`);
  process.exit(0);
}

const piRoot = dirname(dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"))));
const piBin = join(piRoot, "dist", "bundle", "cli.js");
if (args.includes("--pi-help")) {
  const result = spawnSync(process.execPath, [piBin, "--help"], { stdio: "inherit" });
  process.exit(result.status ?? 2);
}
// Pi's raw loader/tool flags bypass Research's package selection and activation.
const forbiddenFlags = new Set(["--extension", "-e", "--no-extensions", "-ne", "--tools", "-t", "--exclude-tools", "-xt", "--no-tools", "-nt", "--no-builtin-tools", "-nbt"]);
const valueFlags = new Set(["--workspace", "--permission", "--execution", "--memory", "--ui-avatar", "--ui-theme", "--config", "--model-profile", "--mcp-config", "--package-config", "--instructions", "--skill", "--max-turns", "--max-seconds", "--max-tokens", "--max-cost-usd", "--provider", "--model", "--api-key", "--system-prompt", "--append-system-prompt", "--name", "-n", "--session", "--session-id", "--fork", "--session-dir", "--models", "--thinking", "--mode", "--export", "--prompt-template", "--theme", "--use-theme", "--tui-mode"]);
for (let index = 0; index < args.length; index++) {
  if (args[index] === "--") break;
  const flag = args[index].split("=", 1)[0];
  if (forbiddenFlags.has(flag)) {
    console.error(`Amadeus manages extension loading and tool permissions. Use research packages install SOURCE --policy FILE instead of ${flag}.`);
    process.exit(2);
  }
  if (valueFlags.has(args[index])) index++;
}
if (["install", "remove", "update", "list"].includes(args[0])) {
  console.error("Use research packages install|remove|list to manage Pi packages with an explicit tool policy.");
  process.exit(2);
}

try {
  if (args[0] === "configure") { await configure(); process.exit(0); }
  for (const flag of ["--model-profile", "--mcp-config", "--package-config"]) {
    const index = args.indexOf(flag);
    if (index !== -1) {
      const value = args[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${flag}`);
      process.env[{ "--model-profile": "RESEARCH_MODEL_PROFILE", "--mcp-config": "RESEARCH_MCP_CONFIG", "--package-config": "RESEARCH_PACKAGE_CONFIG" }[flag]] = resolve(value);
    }
  }
  loadApiConfig();
  const profile = loadModelProfile();
  if (!process.env.RESEARCH_MODEL && profile.model) process.env.RESEARCH_MODEL = profile.model;
} catch (error) { console.error(error.message); process.exit(2); }

const cacheEnv = join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "research-cli", "python", pkg.version);
function pythonPath() {
  if (process.env.RESEARCH_PYTHON) return process.env.RESEARCH_PYTHON;
  const local = join(root, ".venv", "bin", "python");
  return existsSync(local) ? local : join(cacheEnv, "bin", "python");
}
function checkBackend(python) {
  return spawnSync(python, ["-c", "import mcp; from research_cli import __version__; print(__version__)"], { encoding: "utf8", timeout: 15000 });
}
if (args[0] === "setup") {
  if (process.env.RESEARCH_BUNDLE_ROOT && existsSync(join(process.env.RESEARCH_BUNDLE_ROOT, "bundle.json"))) {
    console.log("Standalone installation already includes Python, MCP and Jev dependencies. Run research configure, then research.");
    process.exit(0);
  }
  const uv = spawnSync("uv", ["--version"], { encoding: "utf8" });
  if (uv.error || uv.status !== 0) {
    console.error("Install uv first: https://docs.astral.sh/uv/getting-started/installation/"); process.exit(2);
  }
  const localCheckout = existsSync(join(root, ".git"));
  const envPath = localCheckout ? join(root, ".venv") : cacheEnv;
  const run = spawnSync("uv", ["sync", "--project", root, "--frozen", "--no-dev", "--extra", "mcp", ...(args.includes("--jev") ? ["--extra", "jev"] : []), "--python", "3.12"], {
    stdio: "inherit", env: { ...process.env, UV_PROJECT_ENVIRONMENT: envPath },
  });
  if (run.error) console.error(run.error.message);
  if (run.status !== 0) process.exit(run.status || 2);
  console.log("Backend installed. Run research doctor, then research."); process.exit(0);
}
const python = pythonPath();
const checked = checkBackend(python);
if (args[0] === "doctor") {
  const api = args.includes("--check-api") ? await checkApi() : { status: "skipped", message: "Use research doctor --check-api for an explicit endpoint access check." };
  console.log(JSON.stringify({ version: pkg.version, pi: pkg.dependencies["@earendil-works/pi-coding-agent"], node: process.versions.node,
    python, standalone: Boolean(process.env.RESEARCH_BUNDLE_ROOT), configFile: configPath(), backend: checked.status === 0 ? checked.stdout.trim() : "missing; run research setup",
    keysPresent: Object.fromEntries(["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "TYPESAFE_API_KEY"].map(k => [k, Boolean(process.env[k])])),
    modelProfile: loadModelProfile(), api,
    verification: args.includes("--check-api") ? "Runtime/import and /models access checks; no generation or tool-call validation." : "Runtime/import checks only; model credentials and endpoint are not validated." }, null, 2));
  process.exit(checked.status === 0 && checked.stdout.trim() === pkg.version && api.status !== "failed" ? 0 : 2);
}
if (checked.status !== 0 || checked.stdout.trim() !== pkg.version) {
  console.error(`Python backend ${pkg.version} unavailable. Run research setup, or set RESEARCH_PYTHON to a matching environment.`);
  process.exit(2);
}
if (args[0] === "project") {
  const action = args[1];
  if (!["backup", "restore", "info"].includes(action)) { console.error("Usage: research project backup|restore|info [arguments]"); process.exit(2); }
  const command = ["-m", "research_cli.maintenance", action, ...args.slice(2)];
  if (!args.includes("--workspace")) command.push("--workspace", process.cwd());
  const result = spawnSync(python, command, { stdio: "inherit", env: process.env });
  if (result.error) console.error("Project maintenance could not start. Check the Python backend.");
  process.exit(result.status ?? 2);
}

const env = { ...process.env, RESEARCH_PYTHON: python, RESEARCH_APPROVAL_SECRET: randomBytes(32).toString("hex"),
  RESEARCH_NODE: process.execPath, RESEARCH_DOCUMENT_PARSER: join(root, "bin", "document-parser.mjs") };
let workspace = process.cwd();
const forwarded = [];
const researchOptions = { "--permission": "RESEARCH_PERMISSION", "--execution": "RESEARCH_EXECUTION", "--memory": "RESEARCH_MEMORY", "--ui-avatar": "RESEARCH_UI_AVATAR", "--ui-theme": "RESEARCH_UI_THEME", "--config": "RESEARCH_CONFIG", "--model-profile": "RESEARCH_MODEL_PROFILE", "--mcp-config": "RESEARCH_MCP_CONFIG", "--package-config": "RESEARCH_PACKAGE_CONFIG", "--instructions": "RESEARCH_INSTRUCTIONS", "--max-turns": "RESEARCH_MAX_TURNS", "--max-seconds": "RESEARCH_MAX_SECONDS", "--max-tokens": "RESEARCH_MAX_TOKENS", "--max-cost-usd": "RESEARCH_MAX_COST_USD" };
const selectedSkills = [];
for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === "--") { forwarded.push(...args.slice(i)); break; }
  if (arg === "--workspace" || arg in researchOptions) {
    const value = args[++i];
    if (!value || value.startsWith("--")) { console.error(`Missing value for ${arg}`); process.exit(2); }
    if (arg === "--workspace") workspace = resolve(value);
    else env[researchOptions[arg]] = ["--config", "--model-profile", "--mcp-config", "--package-config", "--instructions"].includes(arg) ? resolve(value) : value;
  } else if (arg === "--skill") {
    const value = args[++i];
    if (!value || value.startsWith("--")) { console.error("Missing value for --skill"); process.exit(2); }
    selectedSkills.push(resolve(value)); forwarded.push("--skill", resolve(value));
  } else if (arg === "--offline") env.RESEARCH_OFFLINE = "1";
  else if (arg === "--approve-experiments") env.RESEARCH_APPROVE_EXPERIMENTS = "1";
  else forwarded.push(arg);
}
for (const [key, values] of Object.entries({ RESEARCH_PERMISSION: ["ask", "read-only", "workspace-write"], RESEARCH_EXECUTION: ["disabled", "docker", "local"], RESEARCH_MEMORY: ["on", "off"], RESEARCH_UI_AVATAR: ["pixel", "off"], RESEARCH_UI_THEME: ["pixel", "system"] })) {
  if (env[key] && !values.includes(env[key])) { console.error(`Invalid ${key}: ${env[key]}`); process.exit(2); }
}
try { workspace = realpathSync(workspace); } catch { console.error("Workspace does not exist"); process.exit(2); }
try {
  const selection = await loadPackageSelection({ file: env.RESEARCH_PACKAGE_CONFIG, cwd: workspace, root, env });
  env.RESEARCH_PACKAGE_SELECTION = JSON.stringify(selection);
  env.RESEARCH_PACKAGE_CONFIG = selection.configFile;
  for (const path of selection.skills) {
    if (!selectedSkills.includes(path)) { selectedSkills.push(path); forwarded.push("--skill", path); }
  }
} catch (error) { console.error(error.message); process.exit(2); }
env.RESEARCH_TRUSTED_SKILL_PATHS = JSON.stringify(selectedSkills);
env.PI_CODING_AGENT_DIR = env.PI_CODING_AGENT_DIR || packagePaths(env).agentDir;
if (env.OPENAI_BASE_URL && env.RESEARCH_MODEL && !forwarded.includes("--model")) forwarded.unshift("--provider", "research-endpoint", "--model", env.RESEARCH_MODEL);
else if (env.RESEARCH_MODEL && !forwarded.includes("--model")) forwarded.unshift("--model", env.RESEARCH_MODEL);

const startupDirectory = mkdtempSync(join(tmpdir(), "research-startup-"));
env.RESEARCH_STARTUP_FILE = join(startupDirectory, "ready");
env.RESEARCH_STARTUP_TOKEN = randomBytes(32).toString("hex");
let ready = false, failed = false;
function checkReady() {
  if (ready) return true;
  try {
    const info = lstatSync(env.RESEARCH_STARTUP_FILE);
    ready = info.isFile() && !info.isSymbolicLink() && info.size === env.RESEARCH_STARTUP_TOKEN.length && readFileSync(env.RESEARCH_STARTUP_FILE, "utf8") === env.RESEARCH_STARTUP_TOKEN;
  } catch { /* An extension still initializing has not written its receipt. */ }
  return ready;
}
const interactive = shouldUseResearchTui(forwarded);
const child = spawn(process.execPath, [interactive ? join(root, "bin", "interactive.mjs") : piBin,
  "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files",
  "--no-builtin-tools",
  "--extension", join(root, "pi", "research.ts"),
  // Explicit skills are loaded while ambient skill discovery remains disabled.
  "--skill", join(root, "pi", "skills"),
  ...forwarded,
], { cwd: workspace, env, stdio: "inherit" });
const poll = setInterval(() => { if (checkReady()) { clearInterval(poll); clearTimeout(startupTimeout); } }, 50);
let forceKill;
const startupTimeout = setTimeout(() => {
  if (checkReady()) return;
  failed = true;
  console.error("Research safety and package initialization did not finish within 30 seconds; stopping the agent.");
  child.kill("SIGTERM");
  forceKill = setTimeout(() => child.kill("SIGKILL"), 5000);
}, 30_000);
child.on("error", error => { failed = true; console.error(error.message); process.exitCode = 2; });
const signalHandlers = new Map();
for (const sig of ["SIGTERM", "SIGHUP"]) {
  const handler = () => child.kill(sig);
  signalHandlers.set(sig, handler); process.on(sig, handler);
}
// In a terminal both processes receive Ctrl-C; let Pi use it to cancel the active turn.
const interrupt = () => { if (!process.stdin.isTTY) child.kill("SIGINT"); };
process.on("SIGINT", interrupt);
await new Promise(resolve => child.on("close", (code, signal) => {
  if (!checkReady()) {
    if (!failed) console.error("Research safety and package initialization failed; no agent tools were enabled.");
    failed = true;
  }
  process.exitCode = failed ? 2 : code ?? (signal === "SIGINT" ? 130 : 1);
  resolve();
}));
clearInterval(poll); clearTimeout(startupTimeout); clearTimeout(forceKill);
for (const [sig, handler] of signalHandlers) process.off(sig, handler);
process.off("SIGINT", interrupt);
rmSync(startupDirectory, { recursive: true, force: true });

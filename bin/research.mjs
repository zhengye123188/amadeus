#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const args = process.argv.slice(2);
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 19)) {
  console.error("Research CLI needs Node >=22.19.0. Activate a supported Node version first.");
  process.exit(2);
}
if (args.includes("--version") || args[0] === "version") {
  console.log(`${pkg.version} (Pi ${pkg.dependencies["@earendil-works/pi-coding-agent"]})`);
  process.exit(0);
}
if (args.includes("--help") || args.includes("-h")) {
  console.log(`Research CLI ${pkg.version} — interactive research on Pi

research setup [--jev]                 Install the Python backend using uv
research doctor                        Check runtimes and backend (no model API call)
research [options]                     Open the interactive terminal
research [options] -p "question"        Run a noninteractive prompt

Research options:
  --workspace DIR                      Existing project directory (default: cwd)
  --permission ask|read-only|workspace-write   Default: ask
  --execution disabled|docker|local     Default: disabled; local is unsandboxed
  --approve-experiments                 Explicitly allow experiment calls without dialogs
  --offline                            Disable backend network tools (model may still use network)
  --memory on|off                       Project context/compaction ablation (default: on)
  --config FILE                        Python backend TOML configuration
  --max-turns N                        Model-step limit per prompt (default: 32)
  --max-seconds N                      Time budget per agent run (default: 600)

Pi options pass through: --provider, --model, -p, --mode json, --continue, --resume.
Set provider keys in environment or use /login. OPENAI_BASE_URL + RESEARCH_MODEL
select an OpenAI-compatible endpoint; RESEARCH_API=chat|responses selects protocol.
Interactive commands: /memory /evidence /jobs /research-status /mcp /compact /tree.
For full upstream options: research --pi-help
Python prototype: research-legacy (separate command).
`);
  process.exit(0);
}

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
  console.log(JSON.stringify({ version: pkg.version, pi: pkg.dependencies["@earendil-works/pi-coding-agent"], node: process.versions.node,
    python, backend: checked.status === 0 ? checked.stdout.trim() : "missing; run research setup",
    keysPresent: Object.fromEntries(["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "TYPESAFE_API_KEY"].map(k => [k, Boolean(process.env[k])])),
    verification: "Runtime/import checks only; model credentials and endpoint are not validated." }, null, 2));
  process.exit(checked.status === 0 && checked.stdout.trim() === pkg.version ? 0 : 2);
}
if (checked.status !== 0 || checked.stdout.trim() !== pkg.version) {
  console.error(`Python backend ${pkg.version} unavailable. Run research setup, or set RESEARCH_PYTHON to a matching environment.`);
  process.exit(2);
}

const env = { ...process.env, RESEARCH_PYTHON: python, RESEARCH_APPROVAL_SECRET: randomBytes(32).toString("hex") };
let workspace = process.cwd();
const forwarded = [];
const researchOptions = { "--permission": "RESEARCH_PERMISSION", "--execution": "RESEARCH_EXECUTION", "--memory": "RESEARCH_MEMORY", "--config": "RESEARCH_CONFIG", "--max-turns": "RESEARCH_MAX_TURNS", "--max-seconds": "RESEARCH_MAX_SECONDS" };
for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === "--workspace" || arg in researchOptions) {
    const value = args[++i];
    if (!value || value.startsWith("--")) { console.error(`Missing value for ${arg}`); process.exit(2); }
    if (arg === "--workspace") workspace = resolve(value);
    else env[researchOptions[arg]] = arg === "--config" ? resolve(value) : value;
  } else if (arg === "--offline") env.RESEARCH_OFFLINE = "1";
  else if (arg === "--approve-experiments") env.RESEARCH_APPROVE_EXPERIMENTS = "1";
  else if (arg === "--pi-help") forwarded.push("--help");
  else forwarded.push(arg);
}
for (const [key, values] of Object.entries({ RESEARCH_PERMISSION: ["ask", "read-only", "workspace-write"], RESEARCH_EXECUTION: ["disabled", "docker", "local"], RESEARCH_MEMORY: ["on", "off"] })) {
  if (env[key] && !values.includes(env[key])) { console.error(`Invalid ${key}: ${env[key]}`); process.exit(2); }
}
try { workspace = realpathSync(workspace); } catch { console.error("Workspace does not exist"); process.exit(2); }
const piRoot = dirname(dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"))));
const piBin = join(piRoot, "dist", "bundle", "cli.js");
if (env.OPENAI_BASE_URL && env.RESEARCH_MODEL && !forwarded.includes("--model")) forwarded.unshift("--provider", "research-endpoint", "--model", env.RESEARCH_MODEL);
else if (env.RESEARCH_MODEL && !forwarded.includes("--model")) forwarded.unshift("--model", env.RESEARCH_MODEL);

const child = spawn(process.execPath, [piBin,
  "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files",
  "--extension", join(root, "pi", "research.ts"),
  // Explicit skills are loaded while ambient skill discovery remains disabled.
  "--skill", join(root, "pi", "skills"), "--exclude-tools", "bash,powershell,grep,find,ls",
  ...forwarded,
], { cwd: workspace, env, stdio: "inherit" });
child.on("error", error => { console.error(error.message); process.exitCode = 2; });
for (const sig of ["SIGTERM", "SIGHUP"]) process.on(sig, () => child.kill(sig));
// In a terminal both processes receive Ctrl-C; let Pi use it to cancel the active turn.
process.on("SIGINT", () => { if (!process.stdin.isTTY) child.kill("SIGINT"); });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal === "SIGINT" ? 130 : 1); });

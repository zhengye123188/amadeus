import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { Writable } from "node:stream";

const fields = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "RESEARCH_MODEL", "RESEARCH_API"];
export function configPath(env = process.env) {
  return join(env.XDG_CONFIG_HOME || join(homedir(), ".config"), "research-cli", "api.json");
}
function validate(config) {
  if (!config || typeof config !== "object" || Array.isArray(config) || fields.some(key => typeof config[key] !== "string" || !config[key].trim())) throw new Error("API configuration requires endpoint, key, model and protocol.");
  let url;
  try { url = new URL(config.OPENAI_BASE_URL); } catch { throw new Error("API endpoint must be a plain http(s) URL, not a Markdown link."); }
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("API endpoint must be an http(s) base URL without credentials, query or fragment.");
  if (!["chat", "responses"].includes(config.RESEARCH_API)) throw new Error("API protocol must be chat or responses.");
  if (/[\r\n]/.test(config.OPENAI_API_KEY)) throw new Error("API key must be a single line.");
  return Object.fromEntries(fields.map(key => [key, config[key].trim()]));
}
export function loadApiConfig(env = process.env) {
  const path = configPath(env);
  if (env.RESEARCH_SKIP_CONFIG === "1" || !existsSync(path)) return;
  let config;
  try { config = validate(JSON.parse(readFileSync(path, "utf8"))); }
  catch { throw new Error(`Invalid saved API configuration: ${path}. Run research configure to replace it.`); }
  for (const key of fields) if (env[key] === undefined) env[key] = config[key];
}
export function saveApiConfig(config, env = process.env) {
  const clean = validate(config), path = configPath(env), directory = join(path, "..");
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, JSON.stringify(clean, null, 2) + "\n", { mode: 0o600, flag: "wx" });
    renameSync(temporary, path);
  } finally { rmSync(temporary, { force: true }); }
  return path;
}
export async function configure() {
  if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error("Run research configure in an interactive terminal; API keys are entered with echo disabled.");
  const defaults = { ...process.env };
  try { loadApiConfig(defaults); } catch { /* allow replacement of broken settings */ }
  async function ask(prompt, secret = false) {
    const output = new Writable({ write(chunk, _encoding, callback) { if (!secret) process.stdout.write(chunk); callback(); } });
    const reader = createInterface({ input: process.stdin, output, terminal: true });
    process.stdout.write(prompt);
    try { return (await reader.question("")).trim(); }
    finally { reader.close(); if (secret) process.stdout.write("\n"); }
  }
  console.log("Configure an OpenAI-compatible API. The key is saved only on this computer (owner-readable file).");
  const url = defaults.OPENAI_BASE_URL || "https://api.deepseek.com";
  const model = defaults.RESEARCH_MODEL || "deepseek-v4-pro";
  const protocol = defaults.RESEARCH_API || "chat";
  const config = {
    OPENAI_BASE_URL: await ask(`API base URL [${url}]: `) || url,
    RESEARCH_MODEL: await ask(`Model ID [${model}]: `) || model,
    RESEARCH_API: await ask(`Protocol [${protocol}]: `) || protocol,
    OPENAI_API_KEY: await ask(`API Key (hidden${defaults.OPENAI_API_KEY ? "; Enter keeps existing key" : ""}): `, true) || defaults.OPENAI_API_KEY,
  };
  console.log(`Saved: ${saveApiConfig(config)}\nRun research to start. Environment variables override saved settings. No API request was made.`);
}

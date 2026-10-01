import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { McpServerEntry } from "@earendil-works/pi-coding-agent";
import type { Effect } from "./policy.ts";
export { loadModelProfile, estimateUsageCost, type ModelProfile } from "../bin/model-profile.mjs";

export interface TrustedMcpConfig {
  servers: McpServerEntry[];
  /** Exact local allowlist. Remote annotations are not authorization. */
  effects: Record<string, Effect>;
}
function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function strings(value: unknown, env: NodeJS.ProcessEnv): Record<string, string> {
  if (value === undefined) return {};
  if (!object(value)) throw new Error("Expected environment/header object");
  return Object.fromEntries(Object.entries(value).map(([key, value]) => {
    if (typeof value !== "string" || value.startsWith("!") || /[\r\n]/.test(value)) throw new Error("Command interpolation and multiline environment/header values are disabled");
    const text = value.replace(/\$\{([A-Z_][A-Z0-9_]*)\}/g, (_all, name: string) => {
      if (env[name] === undefined) throw new Error("An MCP configuration environment variable is missing");
      return env[name]!;
    });
    // The native adapter accepts !cmd/$VAR interpolation too. Never let expanded secrets invoke it.
    if (text.startsWith("!") || /\$\{|[\r\n]/.test(text)) throw new Error("Unsafe MCP environment/header value");
    return [key, text];
  }));
}
/** Read only a file explicitly selected by --mcp-config; ambient project config remains disabled. */
export function loadTrustedMcpConfig(file: string | undefined, cwd: string, env = process.env): TrustedMcpConfig {
  if (!file) return { servers: [], effects: {} };
  let document: unknown;
  try {
    const text = readFileSync(file, "utf8");
    if (text.length > 262144) throw new Error();
    document = JSON.parse(text);
  } catch { throw new Error("Invalid trusted MCP JSON file"); }
  if (!object(document) || !object(document.mcpServers) || Object.keys(document).some(key => key !== "mcpServers")) throw new Error("Trusted MCP configuration requires mcpServers");
  const result: TrustedMcpConfig = { servers: [], effects: {} };
  const entries = Object.entries(document.mcpServers);
  if (entries.length > 16) throw new Error("Configure at most 16 external MCP servers");
  for (const [name, value] of entries) {
    if (!/^[a-z][a-z0-9-]{0,30}$/.test(name) || name === "research" || !object(value)) throw new Error("Invalid or reserved MCP server name");
    if (Object.keys(value).some(key => !["command", "args", "env", "cwd", "url", "headers", "timeout", "effects"].includes(key))) throw new Error(`Unsupported configuration for MCP server ${name}`);
    if (!object(value.effects) || !Object.keys(value.effects).length) throw new Error(`MCP server ${name} requires an exact per-tool effects allowlist`);
    const exposure: Record<string, "direct"> = {};
    for (const [tool, effect] of Object.entries(value.effects)) {
      const nativeName = `mcp__${name}__${tool}`;
      // Avoid Pi name sanitizing/hashing aliases, which would weaken an exact policy map.
      if (!/^[A-Za-z_][A-Za-z0-9_-]*$/.test(tool) || nativeName.length > 64 || !["read", "write", "execute", "external"].includes(effect as string)) throw new Error(`Invalid tool allowlist for MCP server ${name}`);
      result.effects[nativeName] = effect as Effect;
      exposure[tool] = "direct";
    }
    const timeout = value.timeout ?? 60;
    if (typeof timeout !== "number" || !Number.isInteger(timeout) || timeout < 1 || timeout > 600) throw new Error(`Invalid timeout for MCP server ${name}`);
    const base = { exposure: "hidden" as const, toolExposure: exposure, timeout };
    let config: McpServerEntry["config"];
    if (typeof value.command === "string" && value.command.trim() && !/[\r\n\0]/.test(value.command) && value.url === undefined) {
      if (value.args !== undefined && (!Array.isArray(value.args) || value.args.some(arg => typeof arg !== "string" || arg.includes("\0")))) throw new Error(`Invalid arguments for MCP server ${name}`);
      if (value.cwd !== undefined && typeof value.cwd !== "string") throw new Error(`Invalid cwd for MCP server ${name}`);
      if (value.headers !== undefined) throw new Error(`Headers require an HTTP MCP server: ${name}`);
      config = { ...base, command: value.command, args: value.args as string[] | undefined, cwd: resolve(cwd, value.cwd as string || "."), env: strings(value.env, env) };
    } else if (typeof value.url === "string" && value.command === undefined) {
      let url: URL;
      try { url = new URL(value.url); } catch { throw new Error(`Invalid HTTP URL for MCP server ${name}`); }
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error(`Invalid HTTP URL for MCP server ${name}`);
      if (value.env !== undefined || value.args !== undefined || value.cwd !== undefined) throw new Error(`Process settings require a stdio MCP server: ${name}`);
      config = { ...base, url: url.href, headers: strings(value.headers, env) };
    } else throw new Error(`MCP server ${name} requires either command or URL`);
    result.servers.push({ name, config, source: resolve(file), scope: "extension" });
  }
  return result;
}

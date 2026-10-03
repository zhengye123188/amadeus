import { test } from "node:test";
import assert from "node:assert/strict";
import { promisify } from "node:util";
import { execFile } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Theme, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences, visibleWidth } from "@earendil-works/pi-tui";
import { createPixelTheme, PixelFooter, PixelHeader, uiText } from "../../pi/ui.ts";
import { mockEndpoint, ResearchProcess } from "./harness.ts";

function baseTheme() {
  // Use Pi's bundled theme as a real base, without reading user theme directories.
  const sdk = dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent")));
  const data = JSON.parse(readFileSync(join(sdk, "modes/interactive/theme/dark.json"), "utf8"));
  const backgrounds = new Set(["selectedBg", "searchMatchBg", "userMessageBg", "customMessageBg", "toolPendingBg", "toolSuccessBg", "toolErrorBg"]);
  const foreground: Record<string, string | number> = {}, background: Record<string, string | number> = {};
  for (const [token, entry] of Object.entries(data.colors)) {
    let color = entry as string | number;
    while (typeof color === "string" && data.vars[color] !== undefined) color = data.vars[color];
    (backgrounds.has(token) ? background : foreground)[token] = color;
  }
  return new Theme(
    foreground as ConstructorParameters<typeof Theme>[0],
    background as ConstructorParameters<typeof Theme>[1],
    "truecolor", { name: "fixture-base", appearance: "dark" },
  );
}

function uiContext(monochrome = false) {
  const ctx = {
    cwd: "/tmp/科研项目 含空格/" + "非常长的项目目录".repeat(12),
    mode: "tui",
    model: { id: "fixture-model", provider: "research-endpoint" },
    ui: { theme: createPixelTheme(baseTheme(), monochrome) },
    getContextUsage: () => ({ tokens: 1024, contextWindow: 8192, percent: 12.5 }),
    sessionManager: { getEntries: () => [], getSessionId: () => "ui-fixture", getBranch: () => [] },
    isIdle: () => true,
  } as unknown as ExtensionContext;
  return ctx;
}

const terminalText = (lines: string[]) => lines.map(stripTerminalSequences).join("\n");

test("pixel header and footer fit narrow terminals, Chinese paths and avatar fallback", () => {
  const ctx = uiContext();
  const data = {
    getGitBranch: () => "codex/像素界面-" + "branch".repeat(12),
    getExtensionStatuses: () => new Map([
      ["research", "research · workspace-write · experiments:disabled · memory:on"],
      ["research-agents", "agents 2/3 · literature, documents"],
    ]),
    getAvailableProviderCount: () => 1,
    onBranchChange: (_callback: () => void) => () => {},
  };
  const pi = { getSessionName: () => "科研会话", getThinkingLevel: () => "off" } as unknown as ExtensionAPI;
  const footer = new PixelFooter(ctx, data, pi, {});
  try {
    for (const avatar of [false, true]) {
      const header = new PixelHeader(ctx, { version: "0.5.0", avatar });
      for (const width of [1, 16, 40, 54, 80, 120]) {
        for (const [name, component] of [["header", header], ["footer", footer]] as const) {
          for (const line of component.render(width)) {
            assert(visibleWidth(line) <= width, `${name} exceeds ${width} columns: ${JSON.stringify(line)}`);
            assert(!line.includes("\n"), "Each rendered row must contain a single terminal line");
          }
        }
      }
    }
  } finally { footer.dispose(); }
});

test("terminal labels neutralize escape sequences, line breaks and bidi controls", () => {
  const unsafe = "科研\x1b]0;malicious-title\x07\x1b[2J\nworkspace\r\t\u202e\u2066file\u2069";
  const safe = uiText(unsafe);
  assert(safe.includes("科研") && safe.includes("workspace") && safe.includes("file"));
  assert(!/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(safe));
  assert(!safe.includes("malicious-title"), "OSC payload must not become a visible workspace label");
});

test("pixel footer preserves extension statuses and updates model, usage and branch live", () => {
  const ctx = uiContext();
  ctx.cwd = "/tmp/research";
  let branch = "main", disposed = 0, renders = 0;
  let branchChanged: (() => void) | undefined;
  const statuses = new Map([["research", "research · read-only · memory:on"]]);
  const data = {
    getGitBranch: () => branch,
    getExtensionStatuses: () => statuses,
    getAvailableProviderCount: () => 1,
    onBranchChange: (callback: () => void) => { branchChanged = callback; return () => { disposed++; }; },
  };
  const pi = { getSessionName: () => "", getThinkingLevel: () => "off" } as unknown as ExtensionAPI;
  const footer = new PixelFooter(ctx, data, pi, {}, () => { renders++; });
  try {
    const initial = terminalText(footer.render(120));
    assert(initial.includes("fixture-model"));
    assert(initial.includes("read-only") && initial.includes("memory:on"));
    ctx.model = { ...ctx.model, id: "fixture-changed" } as NonNullable<ExtensionContext["model"]>;
    ctx.getContextUsage = () => undefined;
    statuses.set("research-agents", "agents 2/3 · literature, documents");
    branch = "codex/pixel-ui";
    branchChanged?.();
    const updated = terminalText(footer.render(120));
    assert(updated.includes("fixture-changed"));
    assert(!updated.includes("fixture-model"));
    assert(updated.includes("agents 2/3"));
    assert(updated.includes("codex/pixel-ui"));
    assert(updated.includes("ctx ?"), "Unavailable context usage must not be reported as zero");
    assert(renders > 0, "Branch changes must request a redraw");
  } finally { footer.dispose(); }
  assert.equal(disposed, 1, "Footer disposal removes the branch listener");
});

test("avatar can be disabled and monochrome headers remain usable without RGB or image protocols", () => {
  const colorful = uiContext();
  const enabled = new PixelHeader(colorful, { version: "0.5.0", avatar: true }).render(120);
  const disabled = new PixelHeader(colorful, { version: "0.5.0", avatar: false }).render(120);
  assert(enabled.some(line => line.includes("▀")), "The default avatar must render visible pixel blocks");
  assert(!disabled.some(line => line.includes("▀")), "Avatar-off must remove the portrait");
  const shortTerminal = new PixelHeader(colorful, { version: "0.5.0", avatar: true, getRows: () => 23 }).render(120);
  assert(!shortTerminal.some(line => line.includes("▀")), "Short terminals preserve room for the conversation");
  assert(shortTerminal.length < disabled.length);
  const ctx = uiContext(true);
  const plain = new PixelHeader(ctx, { version: "0.5.0", avatar: true, monochrome: true }).render(120);
  assert(terminalText(plain).match(/Research CLI/i));
  assert(!plain.join("").match(/\x1b\[(?:38|48);2;/), "NO_COLOR fallback must not emit RGB color escapes");
  assert(!plain.join("").includes("\x1b]1337;File=") && !plain.join("").includes("\x1b_G"));
  for (const line of plain) assert(visibleWidth(line) <= 120);
});

test("real Pi: terminal personalization preserves clean RPC and JSON protocols", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-ui-protocols-"));
  const workspace = join(root, "科研项目 空格");
  mkdirSync(workspace);
  const uiEnv = {
    HOME: join(root, "home"),
    XDG_CONFIG_HOME: join(root, "config"),
    XDG_CACHE_HOME: join(root, "cache"),
    XDG_DATA_HOME: join(root, "data"),
    RESEARCH_UI: "pixel",
    RESEARCH_UI_AVATAR: "pixel",
    TERM: "xterm-kitty",
    TERM_PROGRAM: "iTerm.app",
  };
  const endpoint = await mockEndpoint(() => ({ text: "Headless protocol fixture completed." }));
  const app = new ResearchProcess(workspace, join(root, "rpc-agent"), endpoint.url, [], uiEnv);
  try {
    await app.prompt("Check the RPC protocol.");
    assert.equal((await app.command("get_last_assistant_text")).text, "Headless protocol fixture completed.");
    assert.equal(app.stderr, "", "RPC stdout must contain only parsed JSON events, with no terminal decorations");
    assert(app.events.some(event => event.type === "agent_settled"));
    await app.close();
    const printed = promisify(execFile)(process.execPath, [
      resolve("bin/research.mjs"), "--workspace", workspace, "--mode", "json", "--offline",
      "--permission", "workspace-write", "-p", "Check the JSON protocol.",
    ], {
      cwd: process.cwd(),
      env: {
        ...process.env, ...uiEnv,
        RESEARCH_SKIP_CONFIG: "1",
        PI_CODING_AGENT_DIR: join(root, "json-agent"),
        PI_OFFLINE: "1", PI_TELEMETRY: "0",
        RESEARCH_PYTHON: process.env.RESEARCH_PYTHON || resolve(".venv/bin/python"),
        OPENAI_BASE_URL: endpoint.url, OPENAI_API_KEY: "local-test-only",
        RESEARCH_MODEL: "fixture", RESEARCH_API: "chat",
      },
      timeout: 30000,
      maxBuffer: 4 * 1024 * 1024,
    });
    // Pi accepts piped input before print mode; close the unused fixture input.
    printed.child.stdin?.end();
    const result = await printed;
    assert(!result.stdout.includes("\x1b"), "JSON output must not include ANSI or image protocol escapes");
    const events = result.stdout.trim().split("\n").map(line => JSON.parse(line));
    assert(events.some(event => event.type === "agent_settled"));
    assert(events.some(event => event.type === "message_end" && JSON.stringify(event.message).includes("Headless protocol fixture completed.")));
    assert.equal(endpoint.requests.length, 2);
    assert.equal(endpoint.authFailures(), 0);
  } finally {
    await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true });
  }
});

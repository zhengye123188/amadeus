import { test } from "node:test";
import assert from "node:assert/strict";
import { promisify } from "node:util";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { EventEmitter } from "node:events";
import headless from "@xterm/headless";
import { Theme, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { parseColor, styleText, stripTerminalSequences, visibleWidth, Text, TuiMainScreen, type Terminal } from "@earendil-works/pi-tui";
import { createPixelTheme, PixelFooter, PixelHeader, uiText, type PixelBitmap } from "../../pi/ui.ts";
import { watchTerminalResize } from "../../pi/resize.ts";
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

test("resize bursts are debounced, force a final redraw, and dispose cleanly", async () => {
  const source = new EventEmitter();
  let invalidations = 0;
  const forced: boolean[] = [];
  const stop = watchTerminalResize({ invalidate: () => { invalidations++; }, requestRender: force => { forced.push(Boolean(force)); } }, source, 20);
  for (let i = 0; i < 20; i++) source.emit("resize");
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.deepEqual(forced, [true], "A -> B -> A must force a repaint even if dimensions end unchanged");
  assert.equal(invalidations, 1);
  source.emit("resize");
  stop(); stop();
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.equal(source.listenerCount("resize"), 0, "Reload/toggle must not accumulate resize listeners");
  assert.deepEqual(forced, [true], "A disposed header must not repaint a stopped or replacement TUI");
});

test("terminal emulator verifies final glyphs and RGB after narrow, short and rapid round-trip resizes", async () => {
  const screen = new headless.Terminal({ cols: 138, rows: 41, allowProposedApi: true });
  const source = new EventEmitter();
  let resize = () => {};
  const writes: string[] = [];
  const terminal = {
    get columns() { return screen.cols; }, get rows() { return screen.rows; },
    start(_input: unknown, callback: () => void) { resize = callback; }, stop() {},
    write(value: string) { writes.push(value); screen.write(value); },
    hideCursor() {}, showCursor() {}, kittyProtocolActive: false,
  } as unknown as Terminal;
  const ui = new TuiMainScreen(terminal, false);
  const header = new PixelHeader(uiContext(), { version: "fixture", avatar: true, getRows: () => screen.rows });
  ui.addChild(header);
  ui.addChild(new Text("\ninput fixture\nstatus fixture", 0, 0));
  const stop = watchTerminalResize(ui, source, 20);
  const flush = () => new Promise<void>(resolve => screen.write("", resolve));
  const snapshot = () => Array.from({ length: screen.rows }, (_, y) => {
    const line = screen.buffer.active.getLine(screen.buffer.active.viewportY + y)!;
    return Array.from({ length: screen.cols }, (_, x) => {
      const cell = line.getCell(x)!;
      const chars = cell.getChars();
      return [chars, cell.getWidth(), chars.trim() ? cell.getFgColor() : null, cell.getBgColor()];
    });
  });
  const change = (cols: number, rows: number) => { screen.resize(cols, rows); resize(); source.emit("resize"); };
  const settle = async () => { await new Promise(resolve => setTimeout(resolve, 55)); await flush(); };
  try {
    ui.start(); ui.renderNow(true); await flush();
    const initial = snapshot();
    const grid: PixelBitmap["variants"][number] = JSON.parse(readFileSync(new URL("../../pi/assets/kurisu-pixel.json", import.meta.url), "utf8"))
      .variants.find((item: PixelBitmap["variants"][number]) => item.width === 80);
    const reference = new headless.Terminal({ cols: grid.width, rows: grid.height / 2, allowProposedApi: true });
    try {
      const naive = grid.quadrants.map((row, y) => [...row].map((glyph, x) => styleText(glyph, {
        fg: parseColor(grid.palette[grid.foreground[y][x]] ?? "#0b1613"),
        bg: parseColor(grid.palette[grid.background[y][x]] ?? "#0b1613"),
      }, "truecolor")).join("")).join("\r\n");
      await new Promise<void>(resolve => reference.write(naive, resolve));
      for (let y = 0; y < grid.height / 2; y++) for (let x = 0; x < grid.width; x++) {
        const expected = reference.buffer.active.getLine(y)!.getCell(x)!;
        assert.deepEqual(initial[y + 1][138 - 2 - grid.width + x], [expected.getChars(), expected.getWidth(),
          expected.getChars().trim() ? expected.getFgColor() : null, expected.getBgColor()], "Compressed ANSI must preserve the independent per-cell glyph and RGB reference");
      }
      assert(Buffer.byteLength(header.render(138).join("\r\n")) < Buffer.byteLength(naive) * .9,
        "The complete header should need fewer bytes than the uncompressed portrait alone");
    } finally { reference.dispose(); }
    // Shrinking in both axes can reflow or evict old cells even when the next
    // application frame observes the original dimensions again.
    change(40, 18); change(138, 41); await settle();
    assert.deepEqual(snapshot(), initial, "Round-trip resize must restore every original glyph and color");
    assert(writes.slice(1).some(write => write.includes("\x1b[2J\x1b[H")), "Final repair must clear reflowed cells");
    for (const [cols, rows] of [[80, 24], [40, 24], [24, 20], [135, 23], [138, 41], [160, 48]]) {
      change(cols, rows); await settle();
      const expected = header.render(cols).map(stripTerminalSequences);
      for (let y = 0; y < expected.length; y++) {
        assert.equal(screen.buffer.active.getLine(screen.buffer.active.viewportY + y)!.translateToString(false), expected[y], `${cols}x${rows}: row ${y} must match the final header`);
      }
      const afterResize = snapshot();
      // A fresh full paint at the same dimensions must be exactly equivalent,
      // including foreground/background state after compressed ANSI output.
      ui.renderNow(true); await flush();
      assert.deepEqual(snapshot(), afterResize, `${cols}x${rows}: no stale color or duplicate rows after resizing`);
    }
    change(138, 41); await settle();
    assert.deepEqual(snapshot(), initial, "Restoring the original viewport must restore the same complete scene");
  } finally { stop(); ui.stop({ preserveScreen: true }); header.dispose(); screen.dispose(); }
});

test("pixel header and footer fit narrow terminals, Chinese paths and avatar fallback", () => {
  const ctx = uiContext();
  const data = {
    getGitBranch: () => "codex/像素界面-" + "branch".repeat(12),
    getExtensionStatuses: () => new Map([
      ["research", "amadeus · workspace-write · experiments:disabled · memory:on"],
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
      for (const width of [1, 16, 40, 54, 79, 80, 110, 135, 140, 160]) {
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
  const statuses = new Map([["research", "amadeus · read-only · memory:on"]]);
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
  assert(shortTerminal.some(line => /[▀▘▝▖▗▚▞]/.test(line)), "Short terminals retain a smaller full scene");
  assert(shortTerminal.length <= Math.floor(23 * .7));
  const ctx = uiContext(true);
  const plain = new PixelHeader(ctx, { version: "0.5.0", avatar: true, monochrome: true }).render(120);
  assert(terminalText(plain).includes("[A] Amadeus"));
  assert(!plain.join("").match(/\x1b\[(?:38|48);2;/), "NO_COLOR fallback must not emit RGB color escapes");
  assert(!plain.join("").includes("\x1b]1337;File=") && !plain.join("").includes("\x1b_G"));
  for (const line of plain) assert(visibleWidth(line) <= 120);
});

test("avatar grids preserve the full half-body scene and their source provenance", () => {
  const source = readFileSync(new URL("../../pi/assets/kurisu-pixel.png", import.meta.url));
  const bitmap = JSON.parse(readFileSync(new URL("../../pi/assets/kurisu-pixel.json", import.meta.url), "utf8"));
  assert.deepEqual(source, readFileSync(new URL("../../docs/assets/kurisu-concept-reference.png", import.meta.url)),
    "The runtime PNG must be the approved half-body scene");
  assert.equal(bitmap.source.sha256, createHash("sha256").update(source).digest("hex"));
  assert.equal(bitmap.schemaVersion, 5);
  assert.deepEqual(bitmap.variants.map((grid: PixelBitmap["variants"][number]) => [grid.width, grid.height]),
    [[16, 10], [24, 16], [32, 20], [40, 26], [48, 32], [56, 36], [64, 42], [72, 46], [80, 52], [88, 58], [96, 62], [112, 72], [144, 94], [284, 184]]);
  assert.deepEqual(bitmap.source.crop, { x: 0, y: 0, width: bitmap.source.width, height: bitmap.source.height },
    "Preparation must retain the full canvas, including the coat, tie and laboratory props");
  for (const grid of bitmap.variants.filter((grid: PixelBitmap["variants"][number]) => grid.width >= 48)) {
    // Both eyes are on the character's left-center face; the scene's right
    // half contains lab props. Looking for one eye per image half hid cropping.
    const feature = (region: [number, number, number, number], matches: (rgb: number[]) => boolean) => {
      const [left, top, right, bottom] = region;
      for (let y = Math.floor(grid.height * top); y < Math.ceil(grid.height * bottom); y++) {
        for (let x = Math.floor(grid.width * left); x < Math.ceil(grid.width * right); x++) {
          const color = grid.palette[grid.pixels[y][x]];
          if (color && matches(color.slice(1).match(/../g)!.map((channel: string) => Number.parseInt(channel, 16)))) return true;
        }
      }
      return false;
    };
    const indigo = ([r, g, b]: number[]) => b > r + 20 && b > g + 15;
    assert(feature([.35, .30, .43, .43], indigo), `${grid.width}px scene must retain the left indigo iris`);
    assert(feature([.46, .28, .54, .39], indigo), `${grid.width}px scene must retain the right indigo iris`);
    assert(feature([.38, .62, .52, .96], ([r, g, b]) => r > 80 && r > g * 1.8 && r > b * 1.3),
      `${grid.width}px scene must retain the red tie below the face`);
    assert(feature([.73, .56, .94, .67], ([r, g, b]) => g > r + 20 && g > b + 10),
      `${grid.width}px scene must retain the green test-tube caps`);
    assert(feature([.71, .85, .96, .97], ([r, g, b]) => g > r + 20 && g > b + 10),
      `${grid.width}px scene must retain the green books beneath the test tubes`);
    assert(feature([.21, .74, .68, .96], ([r, g, b]) => Math.min(r, g, b) > 150 && Math.max(r, g, b) - Math.min(r, g, b) < 70),
      `${grid.width}px scene must retain the lower white lab coat`);
  }
});

test("original concept extraction is reproducible and retains every original RGB pixel at full size", async () => {
  const bytes = readFileSync(new URL("../../pi/assets/kurisu-pixel.png", import.meta.url));
  const committed = readFileSync(new URL("../../pi/assets/kurisu-pixel.json", import.meta.url));
  const bitmap = JSON.parse(committed.toString("utf8"));
  assert.equal(bitmap.source.colors, "exact-source-rgb");
  assert.deepEqual([bitmap.source.width, bitmap.source.height], [284, 184]);
  const requirePi = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
  const { PhotonImage } = requirePi("@silvia-odwyer/photon-node");
  const source = PhotonImage.new_from_byteslice(bytes);
  let rgba: Uint8Array;
  try { rgba = source.get_raw_pixels(); } finally { source.free(); }
  const originalColors = new Set<string>();
  for (let i = 0; i < rgba.length; i += 4) {
    originalColors.add(`#${Buffer.from(rgba.subarray(i, i + 3)).toString("hex")}`);
  }
  assert.equal(originalColors.size, 19349, "The actual source colors must not be reduced to a global 63-color palette");
  const full = bitmap.variants.at(-1) as PixelBitmap["variants"][number];
  const glyphs = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█";
  for (let y = 0; y < full.height; y++) {
    for (let x = 0; x < full.width; x++) {
      const original = `#${Buffer.from(rgba.subarray((y * full.width + x) * 4, (y * full.width + x) * 4 + 3)).toString("hex")}`;
      assert.equal(full.palette[full.pixels[y][x]], original, "The original grid must preserve each source pixel exactly");
      const mask = glyphs.indexOf(full.quadrants[Math.floor(y / 2)][x]);
      for (const bit of y % 2 ? [4, 8] : [1, 2]) {
        const table = mask & bit ? full.foreground : full.background;
        assert.equal(full.palette[table[Math.floor(y / 2)][x]], original, "Original-size quadrant subpixels must preserve the same source RGB");
      }
    }
  }
  for (const grid of bitmap.variants) {
    for (const color of grid.palette.slice(1)) assert(originalColors.has(color!), "Prepared colors must come from the concept, without invented or averaged RGB");
  }
  const temporary = mkdtempSync(join(tmpdir(), "amadeus-pixels-"));
  try {
    const output = join(temporary, "pixels.json");
    await promisify(execFile)(process.execPath, [resolve("scripts/prepare-pixel-avatar.mjs"), resolve("pi/assets/kurisu-pixel.png"), output]);
    assert.deepEqual(readFileSync(output), committed, "Regenerating pixel data must produce identical committed bytes");
  } finally { rmSync(temporary, { recursive: true, force: true }); }
});

test("concept pixel tables render full scenes at both character densities and preserve editing space", () => {
  const ctx = uiContext();
  const bitmap: PixelBitmap = JSON.parse(readFileSync(new URL("../../pi/assets/kurisu-pixel.json", import.meta.url), "utf8"));
  for (const [width, rows, gridWidth, gridHeight] of [
    [94, 26, 48, 32], [110, 30, 56, 36], [135, 37, 72, 46],
    [138, 41, 80, 52], [160, 48, 96, 62], [180, 60, 112, 72],
    [200, 72, 144, 94], [340, 135, 284, 184],
  ]) {
    const grid = bitmap.variants.find(item => item.width === gridWidth && item.height === gridHeight)!;
    for (const renderer of ["quadrant", "half"] as const) {
      const header = new PixelHeader(ctx, { version: "fixture", avatar: true, bitmap, renderer, getRows: () => rows });
      const lines = header.render(width);
      assert(lines.length <= Math.floor(rows * .7), "The avatar must leave at least 30% of the viewport for editing and dialogue");
      assert.equal(lines.length, gridHeight / 2 + 2, "The full scene must render without vertical clipping");
      for (const line of lines) assert(visibleWidth(line) <= width);
      const plainRows = lines.map(stripTerminalSequences);
      for (let y = 0; y < gridHeight / 2; y++) {
        const expected = renderer === "half" ? "▀".repeat(gridWidth) : grid.quadrants[y];
        assert(plainRows[y + 1].endsWith(expected + " │"), "Terminal glyphs must match the prepared concept data");
      }
      if (renderer === "quadrant") {
        const eyeColors = grid.foreground.flat().concat(grid.background.flat()).map(index => grid.palette[index]).filter(color => color
          && Number.parseInt(color.slice(5, 7), 16) > Number.parseInt(color.slice(1, 3), 16) + 20
          && Number.parseInt(color.slice(5, 7), 16) > Number.parseInt(color.slice(3, 5), 16) + 15);
        assert(eyeColors.length, "The prepared output must retain rare blue iris colors");
        const [r, g, b] = eyeColors[0]!.slice(1).match(/../g)!.map(channel => Number.parseInt(channel, 16));
        assert(lines.join("").includes(`;2;${r};${g};${b}m`), "Stored eye color must reach the terminal");
      }
      assert.deepEqual(header.render(width), lines, "Cached portraits must remain stable");
      header.invalidate();
      assert.deepEqual(header.render(width), lines, "Invalidation must rebuild the same selected pixels");
      assert(!lines.join("").includes("\x1b]1337;File=") && !lines.join("").includes("\x1b_G"), "Pixel rendering must never transmit a PNG");
    }
  }
  for (const [width, rows] of [[80, 36], [93, 41], [135, 23], [138, 25], [54, 32], [40, 24], [24, 20]]) {
    const lines = new PixelHeader(ctx, { version: "fixture", avatar: true, bitmap, getRows: () => rows }).render(width);
    assert(/[▀▄█▘▝▖▗▚▞▌▐▛▜▙▟]/.test(lines.join("")), "Narrow and short terminals retain a complete smaller scene");
    assert(lines.length <= Math.min(Math.floor(rows * .7), rows - 7), "Keep at least seven rows for input and statuses");
    for (const line of lines) assert(visibleWidth(line) <= width);
  }
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

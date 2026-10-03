import { readFileSync } from "node:fs";
import {
  CustomEditor, Theme, type ExtensionAPI, type ExtensionContext,
  type ReadonlyFooterDataProvider, type ThemeBg, type ThemeColor,
} from "@earendil-works/pi-coding-agent";
import {
  parseColor, styleText, truncateToWidth, visibleWidth,
  type Component, type EditorTheme, type TUI,
} from "@earendil-works/pi-tui";

const PANEL = "#0b1613";
const BG_KEYS: ThemeBg[] = ["selectedBg", "searchMatchBg", "userMessageBg", "customMessageBg", "toolPendingBg", "toolSuccessBg", "toolErrorBg"];

export interface PixelGrid {
  width: number;
  height: number;
  palette: (string | null)[];
  pixels: number[][];
}

export interface PixelBitmap {
  schemaVersion: number;
  variants: PixelGrid[];
}

// Terminal titles, paths and extension statuses are data, never terminal instructions.
export function uiText(value: unknown): string {
  return String(value ?? "")
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, " ")
    .replace(/\s+/g, " ").trim();
}

export function createPixelTheme(base: Theme, monochrome = false): Theme {
  const name = monochrome ? "research-mono" : "research-pixel";
  const resource = JSON.parse(readFileSync(new URL(`./themes/${name}.json`, import.meta.url), "utf8")) as { colors: Record<string, string> };
  const fg = {} as Record<ThemeColor, string>;
  const bg = {} as Record<ThemeBg, string>;
  for (const [key, color] of Object.entries(resource.colors)) {
    if (BG_KEYS.includes(key as ThemeBg)) bg[key as ThemeBg] = color;
    else fg[key as ThemeColor] = color;
  }
  return new Theme(fg, bg, base.getColorMode(), { name, appearance: "dark" });
}

function fit(text: string, width: number): string {
  const clipped = truncateToWidth(text, Math.max(0, width), "");
  return clipped + " ".repeat(Math.max(0, width - visibleWidth(clipped)));
}

function panel(text: string, theme: Theme, monochrome: boolean, color: ThemeColor = "text"): string {
  const background = theme.name === "research-pixel" ? parseColor(PANEL) : theme.colors.customMessageBg;
  return monochrome ? text : theme.style(text, { fg: color, bg: background });
}

function readAvatar(): PixelBitmap {
  const bitmap = JSON.parse(readFileSync(new URL("./assets/kurisu-pixel.json", import.meta.url), "utf8")) as PixelBitmap;
  const dimensions = [[32, 20], [48, 32], [64, 40]];
  if (bitmap.schemaVersion !== 3 || !Array.isArray(bitmap.variants) || bitmap.variants.length !== dimensions.length
    || bitmap.variants.some((grid, i) => grid.width !== dimensions[i][0] || grid.height !== dimensions[i][1]
      || !Array.isArray(grid.palette) || grid.palette[0] !== null || grid.palette.length > 64
      || grid.palette.some((color, j) => j > 0 && !/^#[a-f0-9]{6}$/i.test(color ?? ""))
      || !Array.isArray(grid.pixels) || grid.pixels.length !== grid.height || grid.pixels.some(row => !Array.isArray(row) || row.length !== grid.width
        || row.some(index => !Number.isInteger(index) || index < 0 || index >= grid.palette.length)))) {
    throw new Error("Invalid bundled pixel avatar");
  }
  return bitmap;
}

function pixelPortrait(bitmap: PixelGrid, theme: Theme): string[] {
  const pixel = (x: number, y: number) => {
    const color = bitmap.palette[bitmap.pixels[y][x]];
    return color ? parseColor(color) : theme.name === "research-pixel" ? parseColor(PANEL) : theme.colors.customMessageBg;
  };
  const lines: string[] = [];
  for (let y = 0; y < bitmap.height; y += 2) {
    let line = "";
    for (let x = 0; x < bitmap.width; x++) line += styleText("▀", { fg: pixel(x, y), bg: pixel(x, y + 1) }, theme.getColorMode());
    lines.push(line);
  }
  return lines;
}

export interface PixelHeaderOptions {
  version: string;
  avatar: boolean;
  monochrome?: boolean;
  bitmap?: PixelBitmap;
  getRows?: () => number;
}

export class PixelHeader implements Component {
  private bitmap?: PixelBitmap;
  constructor(private ctx: ExtensionContext, private options: PixelHeaderOptions) {
    // No image decoding, native image protocols, or network access in the UI.
    if (options.avatar && !options.monochrome) this.bitmap = options.bitmap ?? readAvatar();
  }
  invalidate() {}
  render(width: number): string[] {
    if (width < 1) return [];
    const { ctx, options } = this;
    const theme = ctx.ui.theme;
    const mono = options.monochrome ?? false;
    const rows = options.getRows?.() ?? 40;
    const compact = width < 60 || rows < 24;
    const avatar = Boolean(this.bitmap) && width >= 80 && !compact;
    // Preserve the entire half-body laboratory scene. Each rectangular grid is
    // prepared from the original PNG, and its height keeps the header <= half
    // the viewport. A 135x37 window uses the 48x32 scene, not a face crop.
    const variant = width >= 140 && rows >= 44 ? 2 : width >= 110 && rows >= 36 ? 1 : 0;
    const grid = avatar ? this.bitmap!.variants[variant] : undefined;
    const portrait = grid ? pixelPortrait(grid, theme) : [];
    const avatarWidth = grid?.width ?? 0;
    const inside = Math.max(0, width - 4);
    const textWidth = Math.max(0, inside - (avatar ? avatarWidth + 2 : 0));
    const model = ctx.model ? `${uiText(ctx.model.provider)} / ${uiText(ctx.model.id)}` : "未选择 · /model";
    const content = compact ? [
      `[A] Amadeus ${uiText(options.version)} · PIXEL LAB`,
      `工作区 ${uiText(ctx.cwd)}`,
      `模型 ${model}`,
    ] : [
      `[A] Amadeus ${uiText(options.version)}`,
      "PIXEL LAB / KURISU",
      "",
      `工作区  ${uiText(ctx.cwd)}`,
      `模型    ${model}`,
      "",
      "从一个研究问题开始。",
      "/research-status  /agents  /memory",
      "/model  /usage  /ui avatar off",
    ];
    if (width < 4) return [fit("Amadeus", width)];
    const count = Math.max(content.length, portrait.length);
    const top = panel(`┌${"─".repeat(width - 2)}┐`, theme, mono, "border");
    const bottom = panel(`└${"─".repeat(width - 2)}┘`, theme, mono, "border");
    const lines = [top];
    for (let row = 0; row < count; row++) {
      const color: ThemeColor = row === 0 ? "accent" : row === 1 && !compact ? "warning" : row > 6 ? "muted" : "text";
      const left = panel(`│ ${fit(content[row] ?? "", textWidth)}`, theme, mono, color);
      const right = avatar ? panel("  ", theme, mono) + (portrait[row] ?? panel(" ".repeat(avatarWidth), theme, mono)) : "";
      lines.push(left + right + panel(" │", theme, mono, "border"));
    }
    lines.push(bottom);
    return lines;
  }
}

export class PixelFooter implements Component {
  private unsubscribe: () => void;
  constructor(
    private ctx: ExtensionContext, private data: ReadonlyFooterDataProvider,
    private pi: Pick<ExtensionAPI, "getThinkingLevel">,
    private options: { monochrome?: boolean } = {}, requestRender: () => void = () => {},
  ) { this.unsubscribe = data.onBranchChange(requestRender); }
  invalidate() {}
  dispose() { this.unsubscribe(); }
  render(width: number): string[] {
    if (width < 1) return [];
    const mono = this.options.monochrome ?? false;
    const theme = this.ctx.ui.theme;
    const usage = this.ctx.getContextUsage();
    const percent = usage?.percent;
    const context = typeof percent === "number" && Number.isFinite(percent)
      ? `ctx ${Math.min(100, Math.max(0, percent)).toFixed(0)}%`
      : "ctx ?";
    const branch = this.data.getGitBranch();
    const model = this.ctx.model ? uiText(this.ctx.model.id) : "/model";
    const meta = `${model} · ${context} · thinking:${uiText(this.pi.getThinkingLevel())}${branch ? ` · git:${uiText(branch)}` : ""}`;
    const statuses = [...this.data.getExtensionStatuses().values()].map(uiText).filter(Boolean);
    // Keep permission/execution/memory and collaboration statuses supplied by the core.
    const lines = [panel(fit(` ${meta}`, width), theme, mono, "muted")];
    for (const status of statuses) lines.push(panel(fit(` ${status}`, width), theme, mono, "accent"));
    return lines;
  }
}

class PixelEditor extends CustomEditor {
  constructor(tui: TUI, theme: EditorTheme, keybindings: ConstructorParameters<typeof CustomEditor>[2], private ctx: ExtensionContext, private monochrome: boolean) {
    super(tui, theme, keybindings, { paddingX: 1, embedWorkingStatus: true });
  }
  protected override renderBottomBorder(width: number, hiddenLineCount: number): string {
    if (hiddenLineCount || width < 45) return super.renderBottomBorder(width, hiddenLineCount);
    const hint = "─ Enter 发送 · / 命令 · Ctrl+D 退出 ";
    const line = fit(hint, width).replace(/ +$/, spaces => "─".repeat(spaces.length));
    return this.monochrome ? line : this.ctx.ui.theme.fg("borderMuted", line);
  }
}

export function registerResearchUI(pi: ExtensionAPI): void {
  let avatar = process.env.RESEARCH_UI_AVATAR !== "off";
  let themeChoice = process.env.RESEARCH_UI_THEME === "system" ? "system" : "pixel";
  const monochrome = process.env.NO_COLOR !== undefined || process.env.TERM === "dumb";
  let originalTheme: Theme | undefined;
  const version = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).version as string;
  const installHeader = (ctx: ExtensionContext) => ctx.ui.setHeader(tui => new PixelHeader(ctx, { version, avatar, monochrome, getRows: () => tui.terminal.rows }));
  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    originalTheme = ctx.ui.getTheme(process.env.RESEARCH_UI_BASE_THEME || "system") ?? ctx.ui.getTheme("system") ?? ctx.ui.theme;
    // Named trusted resources survive Pi's theme reapplication after /new and /reload.
    // The interactive host overrides the initial setting, so startup does not save preferences.
    const selected = monochrome ? "research-mono" : themeChoice === "pixel" ? "research-pixel" : originalTheme.name || "system";
    const result = ctx.ui.setTheme(selected);
    if (!result.success) throw new Error(`Research UI theme unavailable: ${result.error}`);
    installHeader(ctx);
    ctx.ui.setFooter((tui, _theme, data) => new PixelFooter(ctx, data, pi, { monochrome }, () => tui.requestRender()));
    ctx.ui.setEditorComponent((tui, theme, keys) => new PixelEditor(tui, theme, keys, ctx, monochrome));
    ctx.ui.setWorkingMessage("Researching…");
    ctx.ui.setWorkingIndicator({ frames: ["▖", "▘", "▝", "▗"], intervalMs: 180 });
    ctx.ui.setTitle("Amadeus");
  });
  pi.registerCommand("ui", {
    description: "切换像素头像和配色：/ui avatar pixel|off 或 /ui theme pixel|system",
    getArgumentCompletions: prefix => ["avatar pixel", "avatar off", "theme pixel", "theme system"]
      .filter(value => value.startsWith(prefix)).map(value => ({ value, label: value })),
    handler: async (args, ctx) => {
      if (ctx.mode !== "tui") { ctx.ui.notify("/ui is available in the interactive terminal.", "info"); return; }
      const choice = args.trim().split(/\s+/);
      if (choice[0] === "avatar" && ["pixel", "off"].includes(choice[1]) && choice.length === 2) {
        avatar = choice[1] === "pixel";
        process.env.RESEARCH_UI_AVATAR = avatar ? "pixel" : "off";
        installHeader(ctx);
      } else if (choice[0] === "theme" && ["pixel", "system"].includes(choice[1]) && choice.length === 2 && originalTheme) {
        themeChoice = choice[1];
        process.env.RESEARCH_UI_THEME = themeChoice;
        ctx.ui.setTheme(monochrome ? "research-mono" : themeChoice === "pixel" ? "research-pixel" : originalTheme.name || "system");
      } else {
        ctx.ui.notify(`UI: ${themeChoice}, avatar: ${avatar ? "pixel" : "off"}${monochrome ? " (monochrome)" : ""}. /ui avatar pixel|off · /ui theme pixel|system`, "info");
      }
    },
  });
}

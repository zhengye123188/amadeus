import { test } from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync, realpathSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { configPath, loadApiConfig, saveApiConfig } from "../bin/api-config.mjs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("saved API settings are private and explicit environment values win", () => {
  const directory = mkdtempSync(join(tmpdir(), "research-config-"));
  const env = { XDG_CONFIG_HOME: directory };
  try {
    const settings = { OPENAI_BASE_URL: "https://example.test/v1", OPENAI_API_KEY: "fixture-key", RESEARCH_MODEL: "fixture-model", RESEARCH_API: "chat" };
    saveApiConfig(settings, env);
    assert.equal(statSync(configPath(env)).mode & 0o777, 0o600);
    const loaded = { ...env, RESEARCH_MODEL: "explicit-model" };
    loadApiConfig(loaded);
    assert.equal(loaded.OPENAI_API_KEY, "fixture-key");
    assert.equal(loaded.RESEARCH_MODEL, "explicit-model");
    const before = readFileSync(configPath(env), "utf8");
    assert.throws(() => saveApiConfig({ ...settings, OPENAI_BASE_URL: "[https://example.test](https://example.test)" }, env), /plain http/);
    assert.equal(readFileSync(configPath(env), "utf8"), before);
    assert.throws(() => saveApiConfig({ ...settings, OPENAI_API_KEY: "fixture\ninjected" }, env), /single line/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

function launcherFixture() {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "research-launch-fixture-")));
  const checkout = fileURLToPath(new URL("../", import.meta.url));
  const app = join(directory, "app");
  mkdirSync(join(app, "bin"), { recursive: true });
  for (const name of ["research.mjs", "api-config.mjs", "api-doctor.mjs", "model-profile.mjs", "packages.mjs", "ocr.mjs"]) copyFileSync(join(checkout, "bin", name), join(app, "bin", name));
  copyFileSync(join(checkout, "package.json"), join(app, "package.json"));
  const version = JSON.parse(readFileSync(join(app, "package.json"), "utf8")).version;
  const pi = join(app, "node_modules", "@earendil-works", "pi-coding-agent");
  mkdirSync(join(pi, "dist", "bundle"), { recursive: true });
  symlinkSync(join(checkout, "node_modules", "jiti"), join(app, "node_modules", "jiti"), "dir");
  writeFileSync(join(pi, "package.json"), JSON.stringify({ name: "@earendil-works/pi-coding-agent", version: "0.99.1", type: "module", exports: "./dist/index.mjs" }));
  writeFileSync(join(pi, "dist", "index.mjs"), `
    import fs from "node:fs";
    import path from "node:path";
    export const SettingsManager = { inMemory() { return {}; } };
    export class DefaultPackageManager {
      constructor() {}
      listConfiguredPackages() { return []; }
      getInstalledPath(source) { return path.isAbsolute(source) ? source : undefined; }
      async resolveExtensionSources(sources) {
        return { extensions: sources.flatMap(directory => {
          const manifest = JSON.parse(fs.readFileSync(path.join(directory, "package.json"), "utf8"));
          return (manifest.pi?.extensions || []).map(name => ({ path: path.join(directory, name), enabled: true }));
        }) };
      }
    }
  `);
  writeFileSync(join(pi, "dist", "bundle", "cli.js"), `
    import fs from "node:fs";
    const argv = process.argv.slice(2);
    if (argv.includes("--help")) { console.log("Fixture Pi help"); process.exit(0); }
    const names = ["RESEARCH_NODE", "RESEARCH_DOCUMENT_PARSER", "RESEARCH_PACKAGE_CONFIG", "RESEARCH_PACKAGE_SELECTION", "RESEARCH_TRUSTED_SKILL_PATHS", "PI_CODING_AGENT_DIR", "RESEARCH_STARTUP_FILE", "RESEARCH_STARTUP_TOKEN"];
    fs.writeFileSync(process.env.FIXTURE_CAPTURE, JSON.stringify({ argv, cwd: process.cwd(), env: Object.fromEntries(names.map(name => [name, process.env[name]])) }));
    if (process.env.FIXTURE_READY !== "none") fs.writeFileSync(process.env.RESEARCH_STARTUP_FILE, process.env.FIXTURE_READY === "wrong" ? "0".repeat(64) : process.env.RESEARCH_STARTUP_TOKEN, { mode: 0o600 });
    if (process.env.FIXTURE_HANG === "1") setInterval(() => {}, 1000);
  `);
  for (const [name, version, entry] of [
    ["pi-subagents", "0.74.0", null],
    ["pi-docparser", "4.0.0", null],
    ["pi-web-access", "0.35.0", "dist/index.js"],
    ["@upstash/context7-pi", "0.1.2", "extensions/context7.ts"],
  ]) {
    const target = join(app, "node_modules", name);
    mkdirSync(target, { recursive: true });
    writeFileSync(join(target, "package.json"), JSON.stringify({ name, version, pi: { extensions: entry ? [entry] : [] } }));
    if (entry) { mkdirSync(join(target, entry, ".."), { recursive: true }); writeFileSync(join(target, entry), "// Fixture; must never be forwarded as a raw extension.\n"); }
  }
  const python = join(directory, "python");
  writeFileSync(python, `#!/bin/sh\nif [ "$1" = "-c" ]; then printf '%s\\n' '${version}'; else exit 7; fi\n`, { mode: 0o700 });
  const env = { ...process.env };
  for (const name of Object.keys(env)) if (/^(RESEARCH_|XDG_|PI_CODING_AGENT_DIR$|OPENAI_|ANTHROPIC_|GITHUB_TOKEN$|TYPESAFE_API_KEY$)/.test(name)) delete env[name];
  Object.assign(env, { RESEARCH_SKIP_CONFIG: "1", RESEARCH_PYTHON: python, XDG_CONFIG_HOME: join(directory, "config"), XDG_DATA_HOME: join(directory, "data"), XDG_CACHE_HOME: join(directory, "cache"), FIXTURE_CAPTURE: join(directory, "capture.json") });
  const launch = (args, overrides = {}, timeout = 15000) => spawnSync(process.execPath, [join(app, "bin", "research.mjs"), ...args], { cwd: directory, env: { ...env, ...overrides }, encoding: "utf8", timeout });
  return { directory, app, env, launch, cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

test("package commands run before credential parsing and Python checks", () => {
  const fixture = launcherFixture();
  try {
    mkdirSync(join(fixture.env.XDG_CONFIG_HOME, "research-cli"), { recursive: true });
    writeFileSync(configPath(fixture.env), "invalid private configuration");
    const result = fixture.launch(["packages", "list"], { RESEARCH_SKIP_CONFIG: "0", RESEARCH_PYTHON: "/missing/python" });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).bundled.length, 4);
    assert.equal(fixture.launch(["packages", "--help"], { RESEARCH_PYTHON: "/missing/python" }).status, 0);
  } finally { fixture.cleanup(); }
});

test("raw extension and tool flags cannot bypass the Research wrapper", () => {
  const fixture = launcherFixture();
  try {
    for (const flag of ["--extension", "--extension=untrusted.ts", "-e", "--tools", "-t", "--exclude-tools", "-xt", "--no-tools", "-nt", "--no-builtin-tools", "-nbt", "--no-extensions", "-ne"]) {
      const result = fixture.launch([flag], { RESEARCH_PYTHON: "/missing/python" });
      assert.equal(result.status, 2, flag);
      assert.match(result.stderr, /research packages install/);
    }
  } finally { fixture.cleanup(); }
});

test("selected packages and skills reach only the wrapper, with isolated state and builtins disabled", () => {
  const fixture = launcherFixture();
  try {
    const extra = join(fixture.directory, "extra");
    mkdirSync(join(extra, "skills"), { recursive: true });
    writeFileSync(join(extra, "package.json"), JSON.stringify({ name: "fixture-extension", version: "1.0.0", pi: { extensions: ["extension.mjs"], skills: ["skills"] } }));
    writeFileSync(join(extra, "extension.mjs"), "// User-selected tool fixture.\n");
    writeFileSync(join(extra, "skills", "SKILL.md"), "---\nname: fixture-skill\ndescription: Fixture instructions\n---\nFixture.\n");
    const config = join(fixture.directory, "packages.json");
    writeFileSync(config, JSON.stringify({ version: 1, packages: [{ source: "./extra", extensions: ["extension.mjs"], skills: ["skills"], effects: { fixture_lookup: "read" } }] }));
    const result = fixture.launch(["--package-config", "packages.json", "--permission", "read-only", "--offline", "-p", "Fixture prompt"]);
    assert.equal(result.status, 0, result.stderr);
    const capture = JSON.parse(readFileSync(fixture.env.FIXTURE_CAPTURE, "utf8"));
    assert.ok(capture.argv.includes("--no-builtin-tools"));
    assert.equal(capture.argv.filter(arg => arg === "--extension").length, 1);
    assert.equal(capture.argv.includes(join(extra, "extension.mjs")), false);
    assert.equal(capture.argv.includes(join(extra, "skills")), true);
    assert.equal(capture.env.RESEARCH_PACKAGE_CONFIG, config);
    const selection = JSON.parse(capture.env.RESEARCH_PACKAGE_SELECTION);
    assert.ok(selection.extensions.some(entry => entry.path === join(extra, "extension.mjs")));
    assert.ok(JSON.parse(capture.env.RESEARCH_TRUSTED_SKILL_PATHS).includes(join(extra, "skills")));
    assert.equal(capture.env.RESEARCH_NODE, process.execPath);
    assert.equal(capture.env.RESEARCH_DOCUMENT_PARSER, join(fixture.app, "bin", "document-parser.mjs"));
    assert.equal(capture.env.PI_CODING_AGENT_DIR, join(fixture.env.XDG_DATA_HOME, "research-cli", "pi-packages"));
    assert.equal(existsSync(join(capture.env.RESEARCH_STARTUP_FILE, "..")), false);
    const explicit = join(fixture.directory, "explicit-pi-state");
    assert.equal(fixture.launch(["-p", "Fixture"], { PI_CODING_AGENT_DIR: explicit }).status, 0);
    assert.equal(JSON.parse(readFileSync(fixture.env.FIXTURE_CAPTURE, "utf8")).env.PI_CODING_AGENT_DIR, explicit);
  } finally { fixture.cleanup(); }
});

test("missing core initialization fails closed even if Pi exits successfully", () => {
  const fixture = launcherFixture();
  try {
    const result = fixture.launch(["-p", "Fixture"], { FIXTURE_READY: "none" });
    assert.equal(result.status, 2);
    assert.match(result.stderr, /initialization failed/);
    const capture = JSON.parse(readFileSync(fixture.env.FIXTURE_CAPTURE, "utf8"));
    assert.ok(capture.argv.includes("--no-builtin-tools"));
    assert.equal(existsSync(join(capture.env.RESEARCH_STARTUP_FILE, "..")), false);
    assert.equal(fixture.launch(["--pi-help"], { RESEARCH_PYTHON: "/missing/python" }).status, 0);
  } finally { fixture.cleanup(); }
});

test("invalid startup receipts time out and stop Pi after 30 seconds", { timeout: 40000 }, () => {
  const fixture = launcherFixture();
  try {
    const start = Date.now();
    const result = fixture.launch(["-p", "Fixture"], { FIXTURE_READY: "wrong", FIXTURE_HANG: "1" }, 37000);
    assert.equal(result.status, 2, result.stderr);
    assert.match(result.stderr, /within 30 seconds/);
    assert.ok(Date.now() - start >= 29000);
    const capture = JSON.parse(readFileSync(fixture.env.FIXTURE_CAPTURE, "utf8"));
    assert.equal(existsSync(join(capture.env.RESEARCH_STARTUP_FILE, "..")), false);
  } finally { fixture.cleanup(); }
});

test("invalid saved settings never expose their contents in errors", () => {
  const directory = mkdtempSync(join(tmpdir(), "research-bad-config-"));
  const env = { XDG_CONFIG_HOME: directory };
  try {
    saveApiConfig({ OPENAI_BASE_URL: "https://example.test", OPENAI_API_KEY: "fixture", RESEARCH_MODEL: "fixture", RESEARCH_API: "chat" }, env);
    writeFileSync(configPath(env), "BROKEN_PRIVATE_FIXTURE");
    assert.throws(() => loadApiConfig(env), error => /research configure/.test(error.message) && !error.message.includes("BROKEN_PRIVATE_FIXTURE"));
    loadApiConfig({ ...env, RESEARCH_SKIP_CONFIG: "1" });
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("doctor stays offline by default and project maintenance uses the configured backend", () => {
  const directory = mkdtempSync(join(tmpdir(), "research-launcher-"));
  const root = fileURLToPath(new URL("../", import.meta.url));
  const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;
  const python = join(directory, "python");
  try {
    writeFileSync(python, `#!/bin/sh\nif [ "$1" = "-c" ]; then printf '%s\\n' '${version}'; else printf '%s\\n' "$@"; fi\n`, { mode: 0o700 });
    const env = { ...process.env, RESEARCH_SKIP_CONFIG: "1", RESEARCH_PYTHON: python, OPENAI_API_KEY: "private-fixture", OPENAI_BASE_URL: "http://127.0.0.1:1", RESEARCH_MODEL: "fixture" };
    // No actual endpoint request: a closed local port would fail an accidental request.
    for (const name of ["RESEARCH_MODEL_PROFILE", "RESEARCH_CONTEXT_WINDOW", "RESEARCH_MAX_OUTPUT_TOKENS", "RESEARCH_REASONING", "RESEARCH_INPUT", "RESEARCH_INPUT_PRICE", "RESEARCH_OUTPUT_PRICE", "RESEARCH_CACHE_READ_PRICE", "RESEARCH_CACHE_WRITE_PRICE"]) delete env[name];
    const launch = args => spawnSync(process.execPath, [join(root, "bin/research.mjs"), ...args], { cwd: directory, env, encoding: "utf8", timeout: 15000 });
    const doctor = launch(["doctor"]);
    assert.equal(doctor.status, 0, doctor.stderr);
    const data = JSON.parse(doctor.stdout);
    assert.equal(data.api.status, "skipped");
    assert.equal(data.modelProfile.prices.input, null);
    assert.equal(doctor.stdout.includes("private-fixture"), false);
    const project = launch(["project", "info"]);
    assert.equal(project.status, 0, project.stderr);
    assert.equal(project.stdout, `-m\nresearch_cli.maintenance\ninfo\n--workspace\n${realpathSync(directory)}\n`);
    assert.equal(launch(["project", "unknown"]).status, 2);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

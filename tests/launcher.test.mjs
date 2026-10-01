import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync, realpathSync } from "node:fs";
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

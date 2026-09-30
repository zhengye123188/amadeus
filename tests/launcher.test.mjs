import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { configPath, loadApiConfig, saveApiConfig } from "../bin/api-config.mjs";

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

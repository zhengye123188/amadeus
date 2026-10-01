import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadModelProfile, estimateUsageCost } from "../bin/model-profile.mjs";
import { checkApi } from "../bin/api-doctor.mjs";
import { checkVersions, syncVersion } from "../scripts/version.mjs";

test("model profiles preserve unknown prices and explicit environment settings", () => {
  const directory = mkdtempSync(join(tmpdir(), "research-profile-"));
  try {
    const file = join(directory, "model.json");
    writeFileSync(file, JSON.stringify({ model: "saved", contextWindow: 65536, maxTokens: 8192, reasoning: true, input: ["text", "image"], prices: { input: 1, output: 2 } }));
    const profile = loadModelProfile({ RESEARCH_MODEL_PROFILE: file, RESEARCH_MODEL: "explicit", RESEARCH_REASONING: "false", RESEARCH_MAX_OUTPUT_TOKENS: "2048" });
    assert.equal(profile.model, "explicit");
    assert.equal(profile.contextWindow, 65536);
    assert.equal(profile.maxTokens, 2048);
    assert.equal(profile.reasoning, false);
    assert.equal(profile.prices.cacheRead, null);
    assert.equal(profile.pricingKnown, false);
    assert.equal(estimateUsageCost(profile, { input: 1000000, output: 1000000 }), 3);
    assert.equal(estimateUsageCost(profile, { cacheRead: 1 }), null);
    assert.equal(estimateUsageCost(loadModelProfile({}), { input: 1 }), null);
    assert.equal(loadModelProfile({ RESEARCH_INPUT_PRICE: "0" }).prices.input, 0);
    assert.throws(() => loadModelProfile({ RESEARCH_MAX_OUTPUT_TOKENS: "65536" }), /Invalid/);
    assert.throws(() => loadModelProfile({ RESEARCH_INPUT: "text,audio" }), /Invalid/);
    assert.throws(() => loadModelProfile({ RESEARCH_INPUT_PRICE: "NaN" }), /Invalid/);
    writeFileSync(file, '{"OPENAI_API_KEY":"private-fixture"}');
    assert.throws(() => loadModelProfile({ RESEARCH_MODEL_PROFILE: file }), error => !error.message.includes("private-fixture"));
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("API doctor makes only a credential-redacted /models GET and avoids redirects", async () => {
  const env = { OPENAI_BASE_URL: "https://endpoint.test/v1/", OPENAI_API_KEY: "private-fixture", RESEARCH_MODEL: "available" };
  const calls = [];
  const good = await checkApi(env, async (url, options) => {
    calls.push({ url: url.href, options });
    return new Response(JSON.stringify({ data: [{ id: "available" }] }), { status: 200 });
  });
  assert.equal(good.status, "ok");
  assert.equal(good.modelAvailable, true);
  assert.equal(calls[0].url, "https://endpoint.test/v1/models");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.redirect, "manual");
  assert.equal(calls[0].options.headers.Authorization, "Bearer private-fixture");
  const bad = await checkApi(env, async () => new Response("private-fixture in provider error", { status: 401 }));
  assert.equal(bad.reason, "authentication");
  assert.equal(JSON.stringify(bad).includes("private-fixture"), false);
  const redirected = await checkApi(env, async () => new Response("", { status: 302 }));
  assert.equal(redirected.reason, "redirect");
  assert.equal((await checkApi(env, async () => new Response("", { status: 404 }))).status, "unsupported");
  assert.equal((await checkApi(env, async () => new Response('{"data":[]}', { status: 200 }))).reason, "model_not_listed");
  assert.equal((await checkApi({}, async () => { throw new Error("should not call"); })).status, "skipped");
  const invalid = await checkApi({ ...env, OPENAI_BASE_URL: "https://user:private-fixture@example.test" });
  assert.equal(invalid.reason, "invalid_configuration");
  assert.equal(JSON.stringify(invalid).includes("private-fixture"), false);
});

test("API doctor distinguishes timeout without echoing a transport error", async () => {
  const result = await checkApi({ OPENAI_BASE_URL: "https://endpoint.test", OPENAI_API_KEY: "private-fixture" }, (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("private-fixture")))), 10);
  assert.equal(result.reason, "timeout");
  assert.equal(JSON.stringify(result).includes("private-fixture"), false);
});

test("version synchronization changes only release metadata and preserves installer permissions", () => {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const directory = mkdtempSync(join(tmpdir(), "research-version-"));
  const files = ["package.json", "package-lock.json", "pyproject.toml", "src/research_cli/__init__.py", "uv.lock", "packaging/download.sh"];
  try {
    for (const file of files) {
      mkdirSync(dirname(join(directory, file)), { recursive: true });
      writeFileSync(join(directory, file), readFileSync(join(root, file)), { mode: statSync(join(root, file)).mode });
    }
    const previous = checkVersions(directory);
    const before = readFileSync(join(directory, "uv.lock"), "utf8");
    const mode = statSync(join(directory, "packaging/download.sh")).mode;
    assert.equal(syncVersion(directory, "9.8.7"), "9.8.7");
    assert.equal(checkVersions(directory), "9.8.7");
    assert.equal(readFileSync(join(directory, "uv.lock"), "utf8"), before.replace('name = "research-terminal"\nversion = "' + previous + '"', 'name = "research-terminal"\nversion = "9.8.7"'));
    assert.equal(statSync(join(directory, "packaging/download.sh")).mode, mode);
    assert.throws(() => syncVersion(directory, "invalid"), /semantic version/);
    assert.throws(() => syncVersion(directory, "01.2.3"), /semantic version/);
    const pkg = JSON.parse(readFileSync(join(directory, "package.json"), "utf8"));
    pkg.version = "9.8.6";
    writeFileSync(join(directory, "package.json"), JSON.stringify(pkg));
    assert.throws(() => checkVersions(directory), /versions disagree/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

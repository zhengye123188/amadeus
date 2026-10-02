import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { link, lstat, mkdir, mkdtemp, readFile, readdir, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { downloadOcrLicense, handleOcrCommand, inspectOcrModels, installOcrModels, OCR_LICENSE, OCR_MODELS, OCR_TESSDATA_COMMIT, ocrDataDirectory, verifyOcrModel } from "../bin/ocr.mjs";

async function fixture(t) {
  const root = await mkdtemp(join(realpathSync(tmpdir()), "research-ocr-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const env = { XDG_CONFIG_HOME: root };
  const payloads = Object.fromEntries(Object.keys(OCR_MODELS).map(language => [language, Buffer.from(`model fixture ${language}`)]));
  const manifest = Object.fromEntries(Object.entries(payloads).map(([language, data]) => [language, {
    ...OCR_MODELS[language], size: data.length, sha256: createHash("sha256").update(data).digest("hex"),
  }]));
  const requests = [];
  const fetch = async (url, options) => {
    requests.push({ url, options });
    const language = new URL(url).pathname.split("/").at(-1).replace(".traineddata", "");
    return new Response(payloads[language], { headers: { "Content-Length": String(payloads[language].length) } });
  };
  return { root, env, directory: ocrDataDirectory(env), manifest, payloads, requests, fetch };
}

test("OCR manifest pins the three official assets and supports an explicit data directory", () => {
  assert.equal(OCR_TESSDATA_COMMIT, "87416418657359cb625c412a48b6e1d6d41c29bd");
  assert.deepEqual(Object.keys(OCR_MODELS), ["eng", "chi_sim", "chi_tra"]);
  assert.deepEqual(Object.values(OCR_MODELS).map(model => model.size), [4113088, 2469156, 2366642]);
  for (const model of Object.values(OCR_MODELS)) {
    assert.match(model.sha256, /^[a-f0-9]{64}$/);
    assert.equal(model.url, `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/${OCR_TESSDATA_COMMIT}/${model.language}.traineddata`);
    assert.equal(Object.isFrozen(model), true);
  }
  assert.equal(ocrDataDirectory({ XDG_CONFIG_HOME: "/private/tmp/config" }), "/private/tmp/config/research-cli/tessdata");
  assert.equal(ocrDataDirectory({ RESEARCH_OCR_TESSDATA: "/private/tmp/selected" }), "/private/tmp/selected");
  assert.equal(OCR_LICENSE.url, `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/${OCR_TESSDATA_COMMIT}/LICENSE`);
  assert.equal(OCR_LICENSE.size, 11358);
  assert.equal(OCR_LICENSE.sha256, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30");
  assert.equal(Object.isFrozen(OCR_LICENSE), true);
});

test("redistributed OCR license is downloaded only from the pinned source and verified", async () => {
  let requested;
  await assert.rejects(downloadOcrLicense({ fetch: async (url, options) => {
    requested = { url, options };
    return new Response("unverified license");
  } }), /pinned size\/checksum verification/);
  assert.equal(requested.url, OCR_LICENSE.url);
  assert.equal(requested.options.signal instanceof AbortSignal, true);
  const cancelled = new AbortController();
  cancelled.abort();
  await assert.rejects(downloadOcrLicense({ signal: cancelled.signal, fetch() { assert.fail("Cancelled license made a request"); } }), /abort/i);
});

test("OCR list is read-only and never creates state or downloads assets", async t => {
  const setup = await fixture(t), output = [];
  assert.equal(await handleOcrCommand(["doctor"], { env: setup.env }), undefined);
  assert.equal(await handleOcrCommand(["ocr", "list"], { env: setup.env, output: value => output.push(JSON.parse(value)), fetch() { assert.fail("Listing downloaded an asset"); } }), 0);
  assert.deepEqual(output[0].models.map(model => model.status), ["missing", "missing", "missing"]);
  assert.equal(existsSync(setup.directory), false);
});

test("explicit default installation verifies bytes, uses private files and skips valid assets on retry", async t => {
  const setup = await fixture(t);
  const result = await installOcrModels(undefined, setup);
  assert.deepEqual(result.models.map(model => [model.language, model.status, model.installed]), [["eng", "ready", true], ["chi_sim", "ready", true]]);
  assert.equal((await lstat(setup.directory)).mode & 0o777, 0o700);
  for (const model of result.models) {
    assert.deepEqual(await readFile(model.path), setup.payloads[model.language]);
    assert.equal((await lstat(model.path)).mode & 0o777, 0o600);
    assert.equal(verifyOcrModel(setup.directory, model.language, setup.manifest).status, "ready");
  }
  assert.equal(setup.requests.length, 2);
  for (const { url, options } of setup.requests) {
    assert.match(url, /raw\.githubusercontent\.com/);
    assert.equal(options.redirect, "manual");
    assert.equal(options.credentials, "omit");
    assert.deepEqual(options.headers, { Accept: "application/octet-stream", "Accept-Encoding": "identity" });
    assert.equal(options.signal instanceof AbortSignal, true);
  }
  const second = await installOcrModels(undefined, { ...setup, fetch() { assert.fail("A valid model was downloaded again"); } });
  assert.equal(second.models.every(model => model.installed === false), true);
  assert.equal((await readdir(setup.directory)).some(name => name.endsWith(".tmp")), false);
});

test("decoded compressed responses use the pinned stream size and digest, not compressed Content-Length", async t => {
  const setup = await fixture(t);
  const result = await installOcrModels(["eng"], { ...setup, fetch: async () => new Response(setup.payloads.eng, {
    headers: { "Content-Encoding": "gzip", "Content-Length": "8" },
  }) });
  assert.equal(result.models[0].status, "ready");
  await assert.rejects(installOcrModels(["chi_sim"], { ...setup, fetch: async () => new Response(Buffer.alloc(setup.payloads.chi_sim.length), {
    headers: { "Content-Encoding": "gzip", "Content-Length": "8" },
  }) }), /checksum/);
});

test("OCR command language selection is an exact allowlist, never arbitrary filenames", async t => {
  const setup = await fixture(t), output = [];
  assert.equal(await handleOcrCommand(["ocr", "install", "--languages", "chi_tra"], { ...setup, output: value => output.push(JSON.parse(value)) }), 0);
  assert.equal(output[0].models[0].language, "chi_tra");
  assert.equal(output[0].models[0].status, "ready");
  for (const languages of ["eng,eng", "../eng", "eng,", "eng+chi_sim", "eng, chi_sim"]) {
    await assert.rejects(handleOcrCommand(["ocr", "install", "--languages", languages], setup), /unique OCR languages/);
  }
  await assert.rejects(handleOcrCommand(["ocr", "install", "--url", "https://other.example/model"], setup), /Usage:/);
  await assert.rejects(handleOcrCommand(["ocr", "list", "--languages", "eng"], setup), /Usage:/);
});

test("failed checksum leaves an existing model intact and produces no temporary residue", async t => {
  const setup = await fixture(t), path = join(setup.directory, "eng.traineddata");
  await mkdir(setup.directory, { recursive: true });
  const original = Buffer.from(setup.payloads.eng);
  original[0] ^= 1;
  await writeFile(path, original);
  assert.equal(verifyOcrModel(setup.directory, "eng", setup.manifest).reason, "checksum mismatch");
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => new Response(original) }), /checksum verification/);
  assert.deepEqual(await readFile(path), original);
  assert.deepEqual(await readdir(setup.directory), ["eng.traineddata"]);
  const repaired = await installOcrModels(["eng"], setup);
  assert.equal(repaired.models[0].status, "ready");
  assert.deepEqual(await readFile(path), setup.payloads.eng);
});

test("pinned sizes reject oversized streams and incorrect Content-Length", async t => {
  const setup = await fixture(t);
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => new Response(Buffer.concat([setup.payloads.eng, Buffer.from("extra")])) }), /size limit/);
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => new Response(setup.payloads.eng, { headers: { "Content-Length": "1" } }) }), /pinned manifest/);
  assert.deepEqual(await readdir(setup.directory), []);
});

test("download redirects cannot leave the official HTTPS host or carry credentials", async t => {
  const setup = await fixture(t);
  for (const location of ["https://untrusted.example/model", "http://raw.githubusercontent.com/model", "https://user:secret@raw.githubusercontent.com/model", "https://raw.githubusercontent.com:8443/model", "https://raw.githubusercontent.com/model?token=anything"]) {
    let requests = 0;
    await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => {
      requests++; return new Response(null, { status: 302, headers: { location } });
    } }), /official raw\.githubusercontent\.com HTTPS host/);
    assert.equal(requests, 1);
  }
  let redirects = 0;
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => {
    redirects++; return new Response(null, { status: 302, headers: { location: OCR_MODELS.eng.url } });
  } }), /redirect limit/);
  assert.equal(redirects, 4);
  let allowedRequests = 0;
  const result = await installOcrModels(["eng"], { ...setup, fetch: async (...args) => {
    allowedRequests++;
    return allowedRequests === 1 ? new Response(null, { status: 302, headers: { location: OCR_MODELS.eng.url } }) : setup.fetch(...args);
  } });
  assert.equal(result.models[0].status, "ready");
});

test("model symlinks and hardlinks are rejected before any download or target modification", async t => {
  const setup = await fixture(t), outside = join(setup.root, "outside.data"), target = join(setup.directory, "eng.traineddata");
  await mkdir(setup.directory, { recursive: true });
  await writeFile(outside, setup.payloads.eng);
  await symlink(outside, target);
  const noDownload = { ...setup, fetch() { assert.fail("Unsafe existing model caused download"); } };
  await assert.rejects(installOcrModels(["eng"], noDownload), /without symlinks or hardlinks/);
  assert.throws(() => inspectOcrModels({ env: setup.env }), /without symlinks or hardlinks/);
  await rm(target);
  await link(outside, target);
  await assert.rejects(installOcrModels(["eng"], noDownload), /without symlinks or hardlinks/);
  assert.deepEqual(await readFile(outside), setup.payloads.eng);
});

test("directory symlinks are rejected, including a missing symlink destination", async t => {
  const setup = await fixture(t), outside = join(setup.root, "outside");
  await mkdir(dirname(setup.directory), { recursive: true });
  await symlink(outside, setup.directory);
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch() { assert.fail("Directory symlink caused download"); } }), /symlinks/);
  assert.throws(() => inspectOcrModels({ env: setup.env }), /symlink aliases/);
  assert.equal(existsSync(outside), false);
});

test("a redirected ancestor is rejected before creating nested directories", async t => {
  const setup = await fixture(t), outside = join(setup.root, "outside"), alias = join(setup.root, "linked-parent");
  await mkdir(outside);
  await symlink(outside, alias);
  const env = { RESEARCH_OCR_TESSDATA: join(alias, "not-created", "tessdata") };
  await assert.rejects(installOcrModels(["eng"], { ...setup, env, fetch() { assert.fail("Ancestor symlink caused download"); } }), /symlinks/);
  assert.deepEqual(await readdir(outside), []);
});

test("macOS system tmp aliases resolve to their actual directories", { skip: process.platform !== "darwin" }, async t => {
  const root = await mkdtemp("/private/tmp/research-ocr-alias-test-");
  t.after(() => rm(root, { recursive: true, force: true }));
  const setup = await fixture(t), env = { RESEARCH_OCR_TESSDATA: join(root.replace("/private/tmp/", "/tmp/"), "tessdata") };
  assert.equal(ocrDataDirectory(env), join(root, "tessdata"));
  assert.equal(inspectOcrModels({ env }).models.every(model => model.status === "missing"), true);
  const result = await installOcrModels(["eng"], { ...setup, env });
  assert.equal(result.directory, join(root, "tessdata"));
  assert.equal(result.models[0].status, "ready");
});

test("target or directory changes during download cannot replace unsafe or redirected files", async t => {
  const setup = await fixture(t), outside = join(setup.root, "outside.data");
  await writeFile(outside, setup.payloads.eng);
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => {
    await link(outside, join(setup.directory, "eng.traineddata"));
    return new Response(setup.payloads.eng);
  } }), /without symlinks or hardlinks/);
  assert.deepEqual(await readFile(outside), setup.payloads.eng);
  await rm(join(setup.directory, "eng.traineddata"));
  await assert.rejects(installOcrModels(["eng"], { ...setup, fetch: async () => {
    await rename(setup.directory, `${setup.directory}.old`);
    await mkdir(setup.directory);
    return new Response(setup.payloads.eng);
  } }), /directory changed during installation/);
  assert.deepEqual(await readdir(setup.directory), []);
});

test("caller cancellation stops installation before requests and before committing downloaded bytes", async t => {
  const setup = await fixture(t), cancelled = new AbortController();
  cancelled.abort();
  await assert.rejects(installOcrModels(["eng"], { ...setup, signal: cancelled.signal }), /abort/i);
  assert.equal(setup.requests.length, 0);
  assert.equal(existsSync(setup.directory), false);
  const controller = new AbortController();
  await assert.rejects(installOcrModels(["eng"], { ...setup, signal: controller.signal, fetch: async () => {
    controller.abort(); return new Response(setup.payloads.eng);
  } }), /abort/i);
  assert.deepEqual(await readdir(setup.directory), []);
});

test("download deadlines bound unresponsive requests, streams and cancellation cleanup", async t => {
  const setup = await fixture(t);
  // AbortSignal.timeout uses an unref'ed timer; keep this deterministic seam alive while waiting.
  const keepAlive = setTimeout(() => {}, 1000);
  t.after(() => clearTimeout(keepAlive));
  await assert.rejects(installOcrModels(["eng"], { ...setup, timeoutMs: 10, fetch: () => new Promise(() => {}) }), /timeout/i);
  let cancelled = false;
  await assert.rejects(installOcrModels(["eng"], { ...setup, timeoutMs: 10, fetch: async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(setup.payloads.eng.subarray(0, 1)); },
    pull() { return new Promise(() => {}); },
    cancel() { cancelled = true; return new Promise(() => {}); },
  })) }), /timeout/i);
  assert.equal(cancelled, true);
  assert.deepEqual(await readdir(setup.directory), []);
  for (const timeoutMs of [0, -1, 1.5, 60001, Infinity]) {
    await assert.rejects(installOcrModels(["eng"], { ...setup, timeoutMs }), /Invalid OCR download timeout/);
  }
});

test("caller cancellation interrupts a response stream that ignores the fetch signal", async t => {
  const setup = await fixture(t), controller = new AbortController();
  const abort = setTimeout(() => controller.abort(), 10);
  t.after(() => clearTimeout(abort));
  let readerCancelled = false;
  await assert.rejects(installOcrModels(["eng"], { ...setup, signal: controller.signal, fetch: async () => new Response(new ReadableStream({
    pull() { return new Promise(() => {}); },
    cancel() { readerCancelled = true; },
  })) }), /abort/i);
  assert.equal(readerCancelled, true);
  assert.deepEqual(await readdir(setup.directory), []);
});

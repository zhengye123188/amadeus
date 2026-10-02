import { createHash, randomUUID } from "node:crypto";
import { chmodSync, closeSync, constants, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readSync, realpathSync, renameSync, rmSync, writeSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";

// Official Apache-2.0 tessdata_fast assets. Installation is always explicit.
export const OCR_TESSDATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd";
const source = `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/${OCR_TESSDATA_COMMIT}`;
export const OCR_MODELS = Object.freeze(Object.fromEntries([
  ["eng", 4113088, "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"],
  ["chi_sim", 2469156, "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730"],
  ["chi_tra", 2366642, "529c5b5797d64b126065cd55f2bb4c7fd7b15790798091b1ff259941a829330b"],
].map(([language, size, sha256]) => [language, Object.freeze({ language, size, sha256, url: `${source}/${language}.traineddata` })])));
export const OCR_LICENSE = Object.freeze({
  url: `${source}/LICENSE`, size: 11358,
  sha256: "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
});
export const OCR_DOWNLOAD_TIMEOUT_MS = 60000;

function normalizeSystemAlias(path) {
  // macOS provides these aliases itself. User-created symlink ancestors still fail below.
  if (process.platform === "darwin") {
    for (const alias of ["/tmp", "/var", "/etc"]) {
      if (path !== alias && !path.startsWith(`${alias}/`)) continue;
      try {
        if (lstatSync(alias).isSymbolicLink() && realpathSync(alias) === `/private${alias}`) {
          return `/private${path}`;
        }
      } catch (error) { if (!missing(error)) throw error; }
    }
  }
  return path;
}
export function ocrDataDirectory(env = process.env) {
  return normalizeSystemAlias(resolve(env.RESEARCH_OCR_TESSDATA || join(env.XDG_CONFIG_HOME || join(homedir(), ".config"), "research-cli", "tessdata")));
}

function modelPath(directory, language) { return join(directory, `${language}.traineddata`); }
function missing(error) { return error?.code === "ENOENT"; }
function directoryIdentity(directory) {
  let info;
  try { info = lstatSync(directory); } catch (error) { if (missing(error)) return undefined; throw error; }
  if (info.isSymbolicLink() || !info.isDirectory() || realpathSync(directory) !== resolve(directory)) {
    throw new Error("OCR data directory must be a real directory without symlink aliases");
  }
  return { dev: info.dev, ino: info.ino };
}
function assertSameDirectory(directory, identity) {
  const current = directoryIdentity(directory);
  if (!current || current.dev !== identity.dev || current.ino !== identity.ino) throw new Error("OCR data directory changed during installation");
}
function ensureDirectory(directory) {
  // Check every existing ancestor before mkdir can follow a redirected parent.
  for (let path = directory; ; path = dirname(path)) {
    try {
      const info = lstatSync(path);
      if (info.isSymbolicLink() || !info.isDirectory()) throw new Error("OCR data directory may not use symlinks or non-directory paths");
    } catch (error) { if (!missing(error)) throw error; }
    if (dirname(path) === path) break;
  }
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const identity = directoryIdentity(directory);
  chmodSync(directory, 0o700);
  return identity;
}
function assertRegularTarget(path) {
  let info;
  try { info = lstatSync(path); } catch (error) { if (missing(error)) return undefined; throw error; }
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) throw new Error("OCR model must be a regular file without symlinks or hardlinks");
  return info;
}
function sameFile(before, after) {
  return before.dev === after.dev && before.ino === after.ino && before.size === after.size
    && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs && after.nlink === 1;
}

/** Read by descriptor with no-follow and identity checks, including replacement during hashing. */
export function verifyOcrModel(directory, language, manifest = OCR_MODELS) {
  const model = manifest[language];
  if (!model) throw new Error("Supported OCR languages: eng, chi_sim, chi_tra");
  const path = modelPath(directory, language), initial = assertRegularTarget(path);
  if (!initial) return { language, status: "missing", path, sha256: model.sha256, size: model.size };
  const handle = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = fstatSync(handle);
    if (!before.isFile() || !sameFile(initial, before)) throw new Error("OCR model changed before verification");
    if (before.size !== model.size) return { language, status: "invalid", path, reason: "size mismatch", sha256: model.sha256, size: model.size };
    const hash = createHash("sha256"), buffer = Buffer.alloc(65536);
    let read, total = 0;
    while ((read = readSync(handle, buffer, 0, Math.min(buffer.length, model.size + 1 - total), null)) > 0) {
      total += read;
      if (total > model.size) throw new Error("OCR model grew during verification");
      hash.update(buffer.subarray(0, read));
    }
    const after = fstatSync(handle), visible = assertRegularTarget(path);
    if (!visible || !sameFile(before, after) || !sameFile(after, visible) || total !== model.size) throw new Error("OCR model changed during verification");
    const valid = hash.digest("hex") === model.sha256;
    return { language, status: valid ? "ready" : "invalid", path, ...(valid ? {} : { reason: "checksum mismatch" }), sha256: model.sha256, size: model.size };
  } finally { closeSync(handle); }
}

/** Listing never creates directories, installs models or makes network requests. */
export function inspectOcrModels({ env = process.env } = {}) {
  const directory = ocrDataDirectory(env);
  const identity = directoryIdentity(directory);
  const models = Object.keys(OCR_MODELS).map(language => verifyOcrModel(directory, language));
  if (identity) assertSameDirectory(directory, identity);
  return { directory, source: `tesseract-ocr/tessdata_fast@${OCR_TESSDATA_COMMIT}`, models };
}

function checkedUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error("Invalid OCR model download URL"); }
  if (url.protocol !== "https:" || url.hostname !== "raw.githubusercontent.com" || url.port && url.port !== "443" || url.username || url.password || url.search || url.hash) {
    throw new Error("OCR model downloads require the official raw.githubusercontent.com HTTPS host");
  }
  return url.href;
}

function cancelBody(body) {
  // Cleanup must not extend the request timeout if a response source stalls during cancellation.
  if (body) Promise.resolve(body.cancel()).catch(() => {});
}
function abortable(operation, signal, onLateValue) {
  return new Promise((resolve, reject) => {
    let finished = false;
    const aborted = () => {
      if (finished) return;
      finished = true;
      reject(signal.reason);
    };
    signal.addEventListener("abort", aborted, { once: true });
    Promise.resolve(operation).then(value => {
      if (finished) { onLateValue?.(value); return; }
      finished = true;
      signal.removeEventListener("abort", aborted);
      resolve(value);
    }, error => {
      if (finished) return;
      finished = true;
      signal.removeEventListener("abort", aborted);
      reject(error);
    });
    if (signal.aborted) aborted();
  });
}
async function downloadModel(model, { fetch, signal }) {
  let url = checkedUrl(model.url), response;
  for (let redirects = 0; redirects <= 3; redirects++) {
    signal.throwIfAborted();
    response = await abortable(fetch(url, { redirect: "manual", credentials: "omit", signal, headers: { Accept: "application/octet-stream", "Accept-Encoding": "identity" } }), signal, value => cancelBody(value.body));
    if (![301, 302, 303, 307, 308].includes(response.status)) break;
    const location = response.headers.get("location");
    cancelBody(response.body);
    if (!location || redirects === 3) throw new Error("OCR model download exceeded the redirect limit");
    url = checkedUrl(new URL(location, url).href);
  }
  if (!response.ok || !response.body) {
    cancelBody(response.body);
    throw new Error(`OCR model download failed (${response.status})`);
  }
  const length = response.headers.get("content-length");
  // Fetch exposes decoded bytes, but Content-Length can describe the compressed
  // transport. The decoded stream still must match the pinned size and digest.
  const encoding = response.headers.get("content-encoding");
  if (length !== null && (!/^\d+$/.test(length) || (!encoding || encoding === "identity") && Number(length) !== model.size)) {
    cancelBody(response.body);
    throw new Error("OCR model download size does not match the pinned manifest");
  }
  const hash = createHash("sha256"), chunks = [];
  let total = 0;
  const reader = response.body.getReader();
  try {
    for (;;) {
      const { done, value: chunk } = await abortable(reader.read(), signal);
      if (done) break;
      if (!(chunk instanceof Uint8Array)) throw new Error("OCR model download returned non-binary bytes");
      total += chunk.length;
      if (total > model.size) throw new Error("OCR model download exceeds the pinned size limit");
      hash.update(chunk); chunks.push(chunk);
    }
  } finally {
    Promise.resolve(reader.cancel()).catch(() => {});
    reader.releaseLock();
  }
  signal.throwIfAborted();
  if (total !== model.size || hash.digest("hex") !== model.sha256) throw new Error("OCR model download failed pinned size/checksum verification");
  return Buffer.concat(chunks, total);
}
/** Standalone builders redistribute the upstream license alongside the pinned model bytes. */
export async function downloadOcrLicense({ fetch = globalThis.fetch, signal } = {}) {
  const boundedSignal = signal ? AbortSignal.any([signal, AbortSignal.timeout(OCR_DOWNLOAD_TIMEOUT_MS)]) : AbortSignal.timeout(OCR_DOWNLOAD_TIMEOUT_MS);
  return downloadModel(OCR_LICENSE, { fetch, signal: boundedSignal });
}
export async function installOcrModels(languages = ["eng", "chi_sim"], { env = process.env, fetch = globalThis.fetch, signal, manifest = OCR_MODELS, timeoutMs = OCR_DOWNLOAD_TIMEOUT_MS } = {}) {
  if (!Array.isArray(languages) || !languages.length || new Set(languages).size !== languages.length || languages.some(language => !Object.hasOwn(OCR_MODELS, language))) {
    throw new Error("Choose unique OCR languages from eng, chi_sim, chi_tra");
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > OCR_DOWNLOAD_TIMEOUT_MS) throw new Error("Invalid OCR download timeout");
  signal?.throwIfAborted();
  const directory = ocrDataDirectory(env), identity = ensureDirectory(directory), results = [];
  for (const language of languages) {
    signal?.throwIfAborted();
    assertSameDirectory(directory, identity);
    // Manifest injection is an internal deterministic-test seam, never a CLI flag or environment setting.
    const model = manifest[language];
    if (!model || model.language !== language || !Number.isSafeInteger(model.size) || model.size < 1 || model.size > 5000000 || !/^[a-f0-9]{64}$/.test(model.sha256)) throw new Error("Invalid pinned OCR model manifest");
    const before = verifyOcrModel(directory, language, manifest);
    if (before.status === "ready") { results.push({ ...before, installed: false }); continue; }
    const downloadSignal = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
    const data = await downloadModel(model, { fetch, signal: downloadSignal });
    assertSameDirectory(directory, identity);
    const path = modelPath(directory, language), temporary = join(directory, `.${language}.${randomUUID()}.tmp`);
    let handle;
    try {
      handle = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      let written = 0;
      while (written < data.length) written += writeSync(handle, data, written, data.length - written);
      fsyncSync(handle); closeSync(handle); handle = undefined;
      downloadSignal.throwIfAborted();
      assertSameDirectory(directory, identity);
      assertRegularTarget(path);
      renameSync(temporary, path);
      const verified = verifyOcrModel(directory, language, manifest);
      if (verified.status !== "ready") throw new Error("Installed OCR model failed verification");
      results.push({ ...verified, installed: true });
    } finally { if (handle !== undefined) closeSync(handle); rmSync(temporary, { force: true }); }
  }
  return { directory, source: `tesseract-ocr/tessdata_fast@${OCR_TESSDATA_COMMIT}`, models: results };
}

/** Returns undefined when the CLI arguments belong to another command. */
export async function handleOcrCommand(args, { output = console.log, ...options } = {}) {
  if (args[0] !== "ocr") return undefined;
  if (args.length === 2 && ["--help", "-h", "help"].includes(args[1])) {
    output("research ocr list\nresearch ocr install [--languages eng,chi_sim,chi_tra]\n\nDefault languages: eng,chi_sim. Downloads verified, pinned official language models only when explicitly requested.");
    return 0;
  }
  let result;
  if (args[1] === "list" && args.length === 2) result = inspectOcrModels(options);
  else if (args[1] === "install" && (args.length === 2 || args.length === 4 && args[2] === "--languages" && args[3])) {
    result = await installOcrModels(args.length === 2 ? undefined : args[3].split(","), options);
  } else throw new Error("Usage: research ocr list | research ocr install [--languages eng,chi_sim,chi_tra]");
  output(JSON.stringify(result, null, 2));
  return 0;
}

#!/usr/bin/env node
// Internal bridge: extraction is owned by pi-docparser, evidence storage by Research CLI.
import { createRequire } from "node:module";
import { constants } from "node:fs";
import { readFile, writeFile, lstat, mkdtemp, mkdir, open, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createJiti } from "jiti";

export const PARSER_VERSION = "4.0.0";
const MAX_BYTES = 20_000_000;
const MAX_PAGES = 200;
const MAX_CHARACTERS = 2_000_000;
const MAX_ARTIFACT_BYTES = 256 * 1024 * 1024;
export const MAX_OCR_PAGES = 20;
export const OCR_DATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd";
export const OCR_MODELS = Object.freeze({
  eng: "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
  chi_sim: "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730",
  chi_tra: "529c5b5797d64b126065cd55f2bb4c7fd7b15790798091b1ff259941a829330b",
});

function ocrLanguages(request) {
  const languages = request.ocrLanguages ?? ["eng"];
  if (!Array.isArray(languages) || !languages.length || languages.length > 3 ||
      new Set(languages).size !== languages.length ||
      languages.some(language => typeof language !== "string" || !Object.hasOwn(OCR_MODELS, language))) {
    throw new Error("OCR languages must be distinct supported codes: eng, chi_sim, chi_tra.");
  }
  return languages;
}

async function snapshotOcrData(request, directory, signal) {
  const languages = ocrLanguages(request);
  if (typeof request.tessdataPath !== "string" || !isAbsolute(request.tessdataPath)) {
    throw new Error("OCR requires a local absolute tessdata path. Run research ocr install first; automatic language downloads are disabled.");
  }
  const target = join(directory, "tessdata");
  await mkdir(target, { mode: 0o700 });
  const models = [];
  for (const language of languages) {
    signal?.throwIfAborted();
    const source = join(request.tessdataPath, `${language}.traineddata`);
    let metadata;
    try { metadata = await lstat(source); }
    catch { throw new Error(`OCR language data ${language} is missing. Run research ocr install --languages ${language}; no automatic download was attempted.`); }
    if (!metadata.isFile() || metadata.size > 8_000_000) throw new Error(`OCR language data ${language} must be a regular file up to 8 MB.`);
    // Read through a no-follow descriptor with a fixed allocation. A changed
    // cache must not turn the size preflight into an unbounded read or redirect
    // it to another file before the private verified snapshot is created.
    const handle = await open(source, constants.O_RDONLY | constants.O_NOFOLLOW);
    let bytes;
    try {
      const before = await handle.stat();
      if (!before.isFile() || before.dev !== metadata.dev || before.ino !== metadata.ino || before.size !== metadata.size) {
        throw new Error(`OCR language data ${language} changed before verification.`);
      }
      const buffer = Buffer.alloc(metadata.size + 1);
      let total = 0;
      while (total < buffer.length) {
        signal?.throwIfAborted();
        const { bytesRead } = await handle.read(buffer, total, Math.min(65536, buffer.length - total), null);
        if (!bytesRead) break;
        total += bytesRead;
      }
      const after = await handle.stat();
      if (total !== metadata.size || after.size !== metadata.size || after.mtimeMs !== before.mtimeMs || after.ctimeMs !== before.ctimeMs) {
        throw new Error(`OCR language data ${language} changed during verification.`);
      }
      bytes = buffer.subarray(0, total);
    } finally { await handle.close(); }
    if (createHash("sha256").update(bytes).digest("hex") !== OCR_MODELS[language]) {
      throw new Error(`OCR language data ${language} failed the pinned SHA256 check. Reinstall the official language model.`);
    }
    // LiteParse downloads only missing files. A private complete snapshot prevents
    // its implicit first-use download, even if the original cache is modified.
    await writeFile(join(target, `${language}.traineddata`), bytes, { mode: 0o600 });
    models.push({ language, sha256: OCR_MODELS[language], source: `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/${OCR_DATA_COMMIT}/${language}.traineddata` });
  }
  return { languages, target, models };
}

async function loadExecutor() {
  const require = createRequire(import.meta.url);
  let metadataPath;
  try {
    metadataPath = require.resolve("pi-docparser/package.json");
  } catch {
    throw new Error("pi-docparser 4.0.0 is not installed. Reinstall Research CLI's npm package.");
  }
  const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
  if (metadata.version !== PARSER_VERSION) {
    throw new Error(`Expected pi-docparser ${PARSER_VERSION}; installed ${metadata.version}. Reinstall Research CLI.`);
  }
  // Node refuses native TS stripping inside node_modules; use Pi's own loader.
  const jiti = createJiti(import.meta.url, { interopDefault: false });
  const { createNativeExecutor } = await jiti.import(
    join(dirname(metadataPath), "extensions", "docparser", "native-executor.ts"),
  );
  return createNativeExecutor({ timeoutMs: 120_000 });
}

export function projectPages(document, expectedPages) {
  if (!document || !Array.isArray(document.pages) || document.pages.length !== expectedPages) {
    throw new Error("pi-docparser did not return every PDF page; partial extraction was rejected.");
  }
  const pages = Array(expectedPages);
  let characters = 0;
  for (const page of document.pages) {
    if (!page || !Number.isInteger(page.pageNum) || page.pageNum < 1 || page.pageNum > expectedPages || typeof page.text !== "string" || pages[page.pageNum - 1] !== undefined) {
      throw new Error("pi-docparser returned invalid or duplicate PDF page numbers.");
    }
    pages[page.pageNum - 1] = page.text;
    // Match Python's Unicode-character budget, including non-BMP text.
    for (const _character of page.text) characters += 1;
    if (characters > MAX_CHARACTERS) throw new Error("Extracted text exceeds 2 million characters");
  }
  if (pages.some(page => typeof page !== "string")) {
    throw new Error("pi-docparser omitted PDF page positions.");
  }
  return pages;
}

export async function parseDocument(request, { signal, executorFactory = loadExecutor } = {}) {
  if (!request || typeof request.inputPath !== "string" || !isAbsolute(request.inputPath) || !Number.isInteger(request.expectedPages) || request.expectedPages < 1 || request.expectedPages > MAX_PAGES) {
    throw new Error("Expected an absolute PDF path and a page count between 1 and 200.");
  }
  if (request.ocr !== undefined && typeof request.ocr !== "boolean") throw new Error("OCR must be an explicit boolean.");
  if (request.ocr && request.expectedPages > MAX_OCR_PAGES) throw new Error("OCR imports are limited to 20 pages per document; split larger PDFs before import.");
  if (!request.ocr && (request.ocrLanguages !== undefined || request.tessdataPath !== undefined)) throw new Error("OCR options require ocr: true.");
  const input = await lstat(request.inputPath);
  if (!input.isFile() || input.size > MAX_BYTES) throw new Error("PDF must be a regular file up to 20 MB.");
  const directory = await mkdtemp(join(tmpdir(), "research-docparser-"));
  let executor;
  try {
    const ocr = request.ocr ? await snapshotOcrData(request, directory, signal) : undefined;
    if (signal?.aborted) throw new Error("Document parsing was cancelled.");
    executor = await executorFactory();
    const outputPath = join(directory, "parsed.json");
    const result = await executor.execute({
      operation: "parse",
      inputPath: request.inputPath,
      stagingDir: join(directory, ".native-parse"),
      outputPath,
      config: {
        outputFormat: "json",
        ocrEnabled: Boolean(ocr),
        ...(ocr ? { ocrLanguage: ocr.languages.join("+"), tessdataPath: ocr.target } : {}),
        numWorkers: 1,
        maxPages: MAX_PAGES,
        dpi: 150,
        preserveVerySmallText: true,
        quiet: true,
      },
    }, { signal });
    if (result.pageCount !== request.expectedPages) throw new Error("PDF page count changed during extraction.");
    const artifact = await lstat(outputPath);
    if (!artifact.isFile() || artifact.size > MAX_ARTIFACT_BYTES) throw new Error("Document parser artifact exceeded its output budget.");
    const document = JSON.parse(await readFile(outputPath, "utf8"));
    return {
      parser: "pi-docparser", version: PARSER_VERSION, ocr: Boolean(ocr),
      ...(ocr ? { ocr_engine: "tesseract", ocr_languages: ocr.languages, ocr_data: ocr.models, dpi: 150 } : {}),
      pages: projectPages(document, request.expectedPages),
    };
  } finally {
    await executor?.dispose();
    await rm(directory, { recursive: true, force: true });
  }
}

async function main() {
  const controller = new AbortController();
  const abort = () => controller.abort();
  process.on("SIGTERM", abort);
  process.on("SIGINT", abort);
  try {
    const chunks = [];
    let bytes = 0;
    for await (const chunk of process.stdin) {
      bytes += chunk.length;
      if (bytes > 64 * 1024) throw new Error("Document parser request exceeds 64 KiB.");
      chunks.push(chunk);
    }
    const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    const result = await parseDocument(request, { signal: controller.signal });
    process.stdout.write(JSON.stringify(result) + "\n");
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  } finally {
    process.off("SIGTERM", abort);
    process.off("SIGINT", abort);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();

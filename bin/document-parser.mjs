#!/usr/bin/env node
// Internal bridge: extraction is owned by pi-docparser, evidence storage by Research CLI.
import { createRequire } from "node:module";
import { readFile, lstat, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createJiti } from "jiti";

export const PARSER_VERSION = "4.0.0";
const MAX_BYTES = 20_000_000;
const MAX_PAGES = 200;
const MAX_CHARACTERS = 2_000_000;
const MAX_ARTIFACT_BYTES = 256 * 1024 * 1024;

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
  const input = await lstat(request.inputPath);
  if (!input.isFile() || input.size > MAX_BYTES) throw new Error("PDF must be a regular file up to 20 MB.");
  const directory = await mkdtemp(join(tmpdir(), "research-docparser-"));
  let executor;
  try {
    executor = await executorFactory();
    const outputPath = join(directory, "parsed.json");
    const result = await executor.execute({
      operation: "parse",
      inputPath: request.inputPath,
      stagingDir: join(directory, ".native-parse"),
      outputPath,
      config: {
        outputFormat: "json",
        ocrEnabled: false,
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
    return { parser: "pi-docparser", version: PARSER_VERSION, ocr: false, pages: projectPages(document, request.expectedPages) };
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

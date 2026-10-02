import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parseDocument, projectPages } from "../bin/document-parser.mjs";

test("page projection preserves blank positions, ordering, and exact text", () => {
  assert.deepEqual(projectPages({ pages: [
    { pageNum: 3, text: "Last page" },
    { pageNum: 1, text: "First page" },
    { pageNum: 2, text: "" },
  ] }, 3), ["First page", "", "Last page"]);
  assert.throws(() => projectPages({ pages: [{ pageNum: 2, text: "source" }] }, 2), /partial extraction/);
  assert.throws(() => projectPages({ pages: [{ pageNum: 1, text: "a" }, { pageNum: 1, text: "b" }] }, 2), /duplicate/);
  assert.throws(() => projectPages({ pages: [{ pageNum: 0, text: "a" }] }, 1), /invalid/);
  assert.throws(() => projectPages({ pages: [{ pageNum: 1, text: "x".repeat(2_000_001) }] }, 1), /2 million/);
});

test("bridge delegates to NativeExecutor without OCR and cleans its artifacts", async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-test-"));
  const inputPath = join(directory, "paper.pdf");
  await writeFile(inputPath, "%PDF-fixture");
  let disposed = false;
  let signalPassed;
  const controller = new AbortController();
  try {
    const result = await parseDocument({ inputPath, expectedPages: 2 }, {
      signal: controller.signal,
      executorFactory: async () => ({
        async execute(job, { signal }) {
          signalPassed = signal;
          assert.equal(job.operation, "parse");
          assert.equal(job.config.outputFormat, "json");
          assert.equal(job.config.ocrEnabled, false);
          assert.equal(job.config.maxPages, 200);
          assert.equal("ocrServerUrl" in job.config, false);
          await writeFile(job.outputPath, JSON.stringify({ pages: [
            { pageNum: 1, text: "" }, { pageNum: 2, text: "Exact source" },
          ] }));
          return { pageCount: 2, outputPath: job.outputPath };
        },
        async dispose() { disposed = true; },
      }),
    });
    assert.deepEqual(result, { parser: "pi-docparser", version: "4.0.0", ocr: false, pages: ["", "Exact source"] });
    assert.equal(signalPassed, controller.signal);
    assert.equal(disposed, true);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("changed page counts fail without a success result and dispose the parser", async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-test-"));
  const inputPath = join(directory, "paper.pdf");
  await writeFile(inputPath, "%PDF-fixture");
  let disposed = false;
  try {
    await assert.rejects(parseDocument({ inputPath, expectedPages: 2 }, {
      executorFactory: async () => ({
        async execute() { return { pageCount: 1 }; },
        async dispose() { disposed = true; },
      }),
    }), /page count changed/);
    assert.equal(disposed, true);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("bundled pi-docparser extracts a real PDF while preserving its blank first page", async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-native-"));
  const inputPath = join(directory, "source.pdf");
  const content = "BT /F1 12 Tf 20 150 Td (Exact source text on page two.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << >> /Contents 4 0 R >>",
    "<< /Length 0 >>\nstream\n\nendstream",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  try {
    await writeFile(inputPath, pdf);
    const result = await parseDocument({ inputPath, expectedPages: 2 });
    assert.deepEqual(result.pages, ["", "Exact source text on page two."]);
    assert.equal(result.ocr, false);
    assert.equal(result.version, "4.0.0");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

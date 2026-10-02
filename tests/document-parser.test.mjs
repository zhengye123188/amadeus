import { test } from "node:test";
import assert from "node:assert/strict";
import { copyFile, lstat, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { deflateSync } from "node:zlib";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parseDocument, projectPages } from "../bin/document-parser.mjs";

function scannedPdf() {
  const glyphs = {
    R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    S: ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    C: ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    H: ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    N: ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
  };
  const width = 1400, height = 260, scale = 12;
  const pixels = Buffer.alloc(width * height, 255);
  for (const [index, character] of Array.from("RESEARCH SCAN").entries()) {
    for (const [row, values] of (glyphs[character] ?? []).entries()) {
      for (const [column, value] of Array.from(values).entries()) {
        if (value === "1") for (let y = 0; y < scale; y++) {
          pixels.fill(0, (70 + row * scale + y) * width + 80 + index * 7 * scale + column * scale,
            (70 + row * scale + y) * width + 80 + index * 7 * scale + (column + 1) * scale);
        }
      }
    }
  }
  const image = deflateSync(pixels);
  const content = "q 700 0 0 130 0 0 cm /Scan Do Q";
  const objects = [
    Buffer.from("<< /Type /Catalog /Pages 2 0 R >>"),
    Buffer.from("<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    Buffer.from("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 700 130] /Resources << /XObject << /Scan 5 0 R >> >> /Contents 4 0 R >>"),
    Buffer.from(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`),
    Buffer.concat([Buffer.from(`<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length ${image.length} >>\nstream\n`), image, Buffer.from("\nendstream")]),
  ];
  const chunks = [Buffer.from("%PDF-1.4\n")], offsets = [0];
  let bytes = chunks[0].length;
  for (const [index, object] of objects.entries()) {
    offsets.push(bytes);
    const chunk = Buffer.concat([Buffer.from(`${index + 1} 0 obj\n`), object, Buffer.from("\nendobj\n")]);
    chunks.push(chunk); bytes += chunk.length;
  }
  chunks.push(Buffer.from(`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${bytes}\n%%EOF\n`));
  return Buffer.concat(chunks);
}

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

test("OCR fails before starting a worker for unavailable, corrupt, or unsupported local language data", async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-ocr-policy-"));
  const inputPath = join(directory, "scan.pdf");
  await writeFile(inputPath, scannedPdf());
  const request = { inputPath, expectedPages: 1, ocr: true, tessdataPath: directory };
  const executorFactory = async () => { throw new Error("worker must not start"); };
  try {
    await assert.rejects(parseDocument(request, { executorFactory }), /missing.*no automatic download/);
    await writeFile(join(directory, "eng.traineddata"), "corrupted model");
    await assert.rejects(parseDocument(request, { executorFactory }), /SHA256/);
    await assert.rejects(parseDocument({ ...request, ocrLanguages: ["eng", "eng"] }, { executorFactory }), /distinct supported/);
    await assert.rejects(parseDocument({ ...request, ocrLanguages: ["..\/secret"] }, { executorFactory }), /distinct supported/);
    await assert.rejects(parseDocument({ ...request, expectedPages: 21 }, { executorFactory }), /20 pages/);
    await assert.rejects(parseDocument({ ...request, ocr: "auto" }, { executorFactory }), /explicit boolean/);
    await rm(join(directory, "eng.traineddata"));
    await symlink(inputPath, join(directory, "eng.traineddata"));
    await assert.rejects(parseDocument(request, { executorFactory }), /regular file/);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(parseDocument(request, { signal: controller.signal, executorFactory }), /aborted/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

const ocrData = process.env.RESEARCH_OCR_TEST_DATA;
test("OCR workers use a complete private language snapshot even if the source cache changes", {
  skip: !ocrData && "set RESEARCH_OCR_TEST_DATA to installed verified language files for the snapshot test",
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-ocr-snapshot-"));
  const inputPath = join(directory, "scan.pdf");
  const sourceModel = join(directory, "eng.traineddata");
  let snapshot;
  await writeFile(inputPath, scannedPdf());
  await copyFile(join(ocrData, "eng.traineddata"), sourceModel);
  const model = await readFile(sourceModel);
  try {
    const result = await parseDocument({ inputPath, expectedPages: 1, ocr: true, tessdataPath: directory }, {
      executorFactory: async () => ({
        async execute(job) {
          snapshot = job.config.tessdataPath;
          assert.notEqual(snapshot, directory);
          assert.equal(job.config.ocrLanguage, "eng");
          assert.equal(job.config.ocrServerUrl, undefined);
          await writeFile(sourceModel, "changed source cache");
          assert.deepEqual(await readFile(join(snapshot, "eng.traineddata")), model);
          await writeFile(job.outputPath, JSON.stringify({ pages: [{ pageNum: 1, text: "snapshot fixture" }] }));
          return { pageCount: 1 };
        },
        async dispose() {},
      }),
    });
    assert.deepEqual(result.pages, ["snapshot fixture"]);
    await assert.rejects(lstat(snapshot), /ENOENT/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("native Tesseract extracts an image-only PDF locally and records the exact model identity", {
  skip: !ocrData && "set RESEARCH_OCR_TEST_DATA to installed verified language files for the real OCR test",
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), "research-parser-native-ocr-"));
  const inputPath = join(directory, "scan.pdf");
  await writeFile(inputPath, scannedPdf());
  try {
    assert.deepEqual((await parseDocument({ inputPath, expectedPages: 1 })).pages, [""]);
    const result = await parseDocument({ inputPath, expectedPages: 1, ocr: true, ocrLanguages: ["eng"], tessdataPath: ocrData });
    assert.match(result.pages[0], /RESEARCH\s+SCAN/);
    assert.equal(result.ocr_engine, "tesseract");
    assert.deepEqual(result.ocr_languages, ["eng"]);
    assert.match(result.ocr_data[0].sha256, /^[a-f0-9]{64}$/);
    assert.match(result.ocr_data[0].source, /87416418657359cb625c412a48b6e1d6d41c29bd\/eng.traineddata$/);
    assert.equal((await lstat(join(ocrData, "eng.traineddata"))).isFile(), true);
    assert.equal((await readFile(join(ocrData, "eng.traineddata"))).length, 4113088);
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

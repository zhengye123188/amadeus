#!/usr/bin/env node
/** Prepare small terminal rendering data without changing the source PNG. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const inputPath = resolve(process.argv[2] ?? fileURLToPath(new URL("../pi/assets/kurisu-pixel.png", import.meta.url)));
const outputPath = resolve(process.argv[3] ?? fileURLToPath(new URL("../pi/assets/kurisu-pixel.json", import.meta.url)));
const gridSizes = [20, 32, 40];
const maxColors = 63; // Palette entry 0 is transparent.
const alphaThreshold = 128;
const bytes = readFileSync(inputPath);
if (bytes.length > 8 * 1024 * 1024 || !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
  throw new Error("Expected a local PNG asset no larger than 8 MiB.");
}

// Pi already ships this exact public image decoder; no image library is needed
// at runtime by the UI, which consumes the committed JSON below.
const piRequire = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
const { PhotonImage } = piRequire("@silvia-odwyer/photon-node");
const image = PhotonImage.new_from_byteslice(bytes);
let rgba;
let width;
let height;
try {
  width = image.get_width();
  height = image.get_height();
  if (width > 4096 || height > 4096 || width < 1 || height < 1) {
    throw new Error("Invalid PNG dimensions.");
  }
  rgba = image.get_raw_pixels();
} finally {
  image.free();
}
if (rgba.length !== width * height * 4) throw new Error("Invalid decoded RGBA data.");

let transparentPixels = 0;
let visiblePixels = 0;
let minX = width;
let minY = height;
let maxX = -1;
let maxY = -1;
for (let y = 0; y < height; y++) {
  for (let x = 0; x < width; x++) {
    const alpha = rgba[(y * width + x) * 4 + 3];
    if (alpha === 0) transparentPixels++;
    if (alpha >= alphaThreshold) {
      visiblePixels++;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
}
if (visiblePixels === 0 || transparentPixels < width * height * 0.05) {
  throw new Error("Expected a nonempty avatar with genuine transparent background.");
}

const visibleBounds = { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
// A head-and-collar close-up of the bundled portrait. The original PNG and its
// transparent background stay intact. Relative coordinates keep preparation
// reproducible if the same artwork is exported at another resolution.
const crop = {
  x: Math.floor(width * 215 / 1254),
  y: Math.floor(height * 20 / 1254),
  width: Math.max(1, Math.floor(width * 815 / 1254)),
  height: Math.max(1, Math.floor(height * 815 / 1254)),
};

// Each terminal size samples the original RGBA bytes independently. In
// particular, the small portrait never downsamples a larger terminal grid;
// that second sampling pass used to skip isolated iris pixels.
function createVariant(gridSize) {
  const scale = gridSize / Math.max(crop.width, crop.height);
  const drawWidth = crop.width * scale;
  const drawHeight = crop.height * scale;
  const left = (gridSize - drawWidth) / 2;
  const top = (gridSize - drawHeight) / 2;
  const samples = Array.from({ length: gridSize }, () => Array(gridSize).fill(null));
  const colors = [];
  for (let y = 0; y < gridSize; y++) {
    for (let x = 0; x < gridSize; x++) {
      if (x + 0.5 < left || x + 0.5 >= left + drawWidth || y + 0.5 < top || y + 0.5 >= top + drawHeight) continue;
      const sx = Math.min(width - 1, crop.x + Math.floor((x + 0.5 - left) / scale));
      const sy = Math.min(height - 1, crop.y + Math.floor((y + 0.5 - top) / scale));
      const offset = (sy * width + sx) * 4;
      if (rgba[offset + 3] < alphaThreshold) continue;
      const color = Array.from(rgba.subarray(offset, offset + 3));
      samples[y][x] = color;
      colors.push(color);
    }
  }
  if (colors.length === 0) throw new Error("The portrait crop contains no visible pixels.");

  const paletteRgb = createPalette(colors);
  const palette = [null, ...paletteRgb.map((color) => `#${color.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`)];
  const nearestIndex = (color) => {
    let nearest = 0;
    let error = Infinity;
    for (let index = 0; index < paletteRgb.length; index++) {
      const candidate = paletteRgb[index].reduce((sum, channel, position) => sum + (channel - color[position]) ** 2, 0);
      if (candidate < error) {
        nearest = index + 1;
        error = candidate;
      }
    }
    return nearest;
  };
  const pixels = samples.map((row) => row.map((color) => color === null ? 0 : nearestIndex(color)));
  if (pixels.length !== gridSize || pixels.some((row) => row.length !== gridSize || row.some((index) => !Number.isInteger(index) || index < 0 || index >= palette.length))) {
    throw new Error("Invalid palette grid.");
  }
  return { width: gridSize, height: gridSize, palette, pixels };
}

// Deterministic median-cut palettes keep the committed JSON small while
// retaining uncommon eye colors alongside the much larger hair region.
const ranges = (box) => [0, 1, 2].map((channel) => {
  const values = box.map((color) => color[channel]);
  return Math.max(...values) - Math.min(...values);
});
function createPalette(colors) {
  const boxes = [colors];
  while (boxes.length < maxColors) {
    let splitIndex = -1;
    let splitChannel = 0;
    let score = -1;
    for (let index = 0; index < boxes.length; index++) {
      const box = boxes[index];
      if (box.length < 2) continue;
      const spread = ranges(box);
      const channel = spread.indexOf(Math.max(...spread));
      const candidate = spread[channel] * Math.sqrt(box.length);
      if (spread[channel] > 0 && candidate > score) {
        score = candidate;
        splitIndex = index;
        splitChannel = channel;
      }
    }
    if (splitIndex === -1) break;
    const box = boxes[splitIndex].sort((a, b) => a[splitChannel] - b[splitChannel] || a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    const middle = Math.floor(box.length / 2);
    boxes.splice(splitIndex, 1, box.slice(0, middle), box.slice(middle));
  }
  return boxes.map((box) => [0, 1, 2].map((channel) => Math.round(box.reduce((sum, color) => sum + color[channel], 0) / box.length)));
}

const variants = gridSizes.map(createVariant);
const result = {
  schemaVersion: 2,
  variants,
  source: {
    filename: basename(inputPath),
    sha256: createHash("sha256").update(bytes).digest("hex"),
    width,
    height,
    crop,
    visibleBounds,
    sourceFocus: "portrait",
    sampling: "nearest-from-source",
    alphaThreshold,
    transparentPixels,
    visiblePixels,
  },
};
writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
console.log(JSON.stringify({
  output: outputPath,
  source: result.source,
  grids: variants.map(({ width, height, palette }) => ({ grid: `${width}x${height}`, paletteColors: palette.length - 1 })),
}));

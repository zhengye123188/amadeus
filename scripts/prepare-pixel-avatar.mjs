#!/usr/bin/env node
/** Extract the selected concept's RGB pixels; this does not redraw the artwork. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const inputPath = resolve(process.argv[2] ?? fileURLToPath(new URL("../pi/assets/kurisu-pixel.png", import.meta.url)));
const outputPath = resolve(process.argv[3] ?? fileURLToPath(new URL("../pi/assets/kurisu-pixel.json", import.meta.url)));
const bytes = readFileSync(inputPath);
if (bytes.length > 8 * 1024 * 1024 || !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
  throw new Error("Expected a local PNG asset no larger than 8 MiB.");
}

// Only the build script decodes the PNG. The CLI reads the committed color
// tables and prints ANSI block characters, including on macOS Terminal.
const piRequire = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
const { PhotonImage } = piRequire("@silvia-odwyer/photon-node");
const image = PhotonImage.new_from_byteslice(bytes);
let rgba, width, height;
try {
  width = image.get_width();
  height = image.get_height();
  if (width < 1 || height < 1 || width > 512 || height > 512 || height % 2) {
    throw new Error("Use a pixel concept no larger than 512x512, with an even height.");
  }
  rgba = image.get_raw_pixels();
} finally { image.free(); }
if (rgba.length !== width * height * 4) throw new Error("Invalid decoded RGBA data.");

const alphaThreshold = 128;
const quadrantGlyphs = [" ", "▘", "▝", "▀", "▖", "▌", "▞", "▛", "▗", "▚", "▐", "▜", "▄", "▙", "▟", "█"];
const quadrantErrorWeights = [2, 4, 3];
const centerPriorWeight = .35;
const transparentRgb = [11, 22, 19]; // Default pixel panel, only for color-error comparison.
function createVariant(gridWidth, gridHeight) {
  const scale = Math.min(gridWidth / width, gridHeight / height);
  const left = (gridWidth - width * scale) / 2;
  const top = (gridHeight - height * scale) / 2;
  const palette = [null];
  const indices = new Map();
  const paletteRgb = [transparentRgb];
  const sample = (x, y, footprintWidth = 0, footprintHeight = 0) => {
    const sx = Math.floor((x - left) / scale);
    const sy = Math.floor((y - top) / scale);
    if (sx < 0 || sy < 0 || sx >= width || sy >= height) return 0;
    let offset = (sy * width + sx) * 4;
    if (rgba[offset + 3] < alphaThreshold) return 0;
    if (footprintWidth && scale < 1) {
      const x0 = Math.max(0, (x - footprintWidth / 2 - left) / scale);
      const x1 = Math.min(width, (x + footprintWidth / 2 - left) / scale);
      const y0 = Math.max(0, (y - footprintHeight / 2 - top) / scale);
      const y1 = Math.min(height, (y + footprintHeight / 2 - top) / scale);
      const candidates = [], mean = [0, 0, 0];
      let area = 0;
      for (let py = Math.floor(y0); py < Math.ceil(y1); py++) {
        for (let px = Math.floor(x0); px < Math.ceil(x1); px++) {
          const position = (py * width + px) * 4;
          if (rgba[position + 3] < alphaThreshold) continue;
          const weight = (Math.min(px + 1, x1) - Math.max(px, x0))
            * (Math.min(py + 1, y1) - Math.max(py, y0));
          area += weight;
          for (let c = 0; c < 3; c++) mean[c] += rgba[position + c] * weight;
          candidates.push(position);
        }
      }
      if (area) {
        // Retain some center contrast so thin dark contours and iris pixels
        // survive area reduction without introducing synthetic RGB colors.
        for (let c = 0; c < 3; c++) mean[c] = mean[c] / area * (1 - centerPriorWeight) + rgba[offset + c] * centerPriorWeight;
        let bestError = Infinity;
        for (const position of candidates) {
          const error = mean.reduce((sum, channel, c) => sum + quadrantErrorWeights[c] * (rgba[position + c] - channel) ** 2, 0);
          if (error < bestError) { bestError = error; offset = position; }
        }
      }
    }
    const rgb = Array.from(rgba.subarray(offset, offset + 3));
    const color = `#${rgb.map(channel => channel.toString(16).padStart(2, "0")).join("")}`;
    if (!indices.has(color)) {
      indices.set(color, palette.length);
      palette.push(color);
      paletteRgb.push(rgb);
    }
    return indices.get(color);
  };
  const pixels = Array.from({ length: gridHeight }, (_, y) => Array.from({ length: gridWidth }, (_, x) => sample(x + .5, y + .5)));

  const colorError = (first, second) => paletteRgb[first].reduce((total, channel, position) =>
    total + quadrantErrorWeights[position] * (channel - paletteRgb[second][position]) ** 2, 0);
  const quadrants = [];
  const foreground = [];
  const background = [];
  for (let y = 0; y < gridHeight; y += 2) {
    let row = "";
    const fgRow = [], bgRow = [];
    for (let x = 0; x < gridWidth; x++) {
      // A terminal cell is approximately twice as tall as it is wide. Each
      // quadrant is half a column wide, but one half-block sample high. Fit the
      // source in physical coordinates before doubling horizontal sampling;
      // treating this 2W x H grid as square pixels would squash the figure.
      // Choose an actual source RGB representative of each subpixel's whole
      // footprint. A single center sample can miss a thin eyelid or finger,
      // or turn one isolated highlight into an oversized block after scaling.
      const tile = [sample(x + .25, y + .5, .5, 1), sample(x + .75, y + .5, .5, 1),
        sample(x + .25, y + 1.5, .5, 1), sample(x + .75, y + 1.5, .5, 1)];
      const unique = [...new Set(tile)].sort((a, b) => a - b);
      if (unique.length === 1) {
        row += " "; fgRow.push(unique[0]); bgRow.push(unique[0]);
        continue;
      }
      // Tiny gradient/noise differences should not create visibly patterned
      // block-glyph edges in otherwise flat regions. Keep an actual tile RGB,
      // and leave the exact original-size mode completely untouched.
      if (scale < 1 && !unique.includes(0) && [0, 1, 2].every(c =>
        Math.max(...unique.map(index => paletteRgb[index][c])) - Math.min(...unique.map(index => paletteRgb[index][c])) <= 3)) {
        const representative = unique.reduce((best, index) =>
          tile.reduce((sum, pixel) => sum + colorError(pixel, index), 0)
          < tile.reduce((sum, pixel) => sum + colorError(pixel, best), 0) ? index : best);
        row += " "; fgRow.push(representative); bgRow.push(representative);
        continue;
      }
      let bestError = Infinity;
      let bestMask = 0, bestBackground = 0, bestForeground = 0;
      for (let a = 0; a < unique.length - 1; a++) {
        for (let b = a + 1; b < unique.length; b++) {
          // Null remains a candidate in mixed padding/opaque cells. This also
          // keeps fully transparent source subpixels genuinely transparent.
          if (unique[0] === 0 && unique[a] !== 0 && unique[b] !== 0) continue;
          const first = unique[a], second = unique[b];
          let error = 0, mask = 0;
          for (let index = 0; index < tile.length; index++) {
            const firstError = colorError(tile[index], first);
            const secondError = colorError(tile[index], second);
            if (secondError < firstError && tile[index] !== 0) {
              error += secondError; mask |= 1 << index;
            } else error += firstError;
          }
          if (error < bestError) {
            bestError = error; bestMask = mask;
            bestBackground = first; bestForeground = second;
          }
        }
      }
      row += quadrantGlyphs[bestMask];
      fgRow.push(bestForeground); bgRow.push(bestBackground);
    }
    quadrants.push(row); foreground.push(fgRow); background.push(bgRow);
  }
  // Every stored RGB value is an actual source pixel. No median-cut palette,
  // invented eye colors, sharpening or repeated resizing is used. Only
  // individual 2x2 cells choose two source-color medoids, since ANSI supplies
  // one foreground and one background color per character.
  return { width: gridWidth, height: gridHeight, palette, pixels, quadrants, foreground, background };
}

const sizes = [[16, 10], [24, 16], [32, 20], [40, 26], [48, 32], [56, 36], [64, 42], [72, 46], [80, 52], [88, 58], [96, 62], [112, 72], [144, 94], [width, height]];
const variants = sizes.filter(([w, h], i) => w <= width && h <= height
  && sizes.findIndex(([otherW, otherH]) => w === otherW && h === otherH) === i)
  .map(([w, h]) => createVariant(w, h));
const result = {
  schemaVersion: 5,
  variants,
  source: {
    filename: basename(inputPath),
    sha256: createHash("sha256").update(bytes).digest("hex"),
    width, height,
    crop: { x: 0, y: 0, width, height },
    sourceFocus: "selected-half-body-concept",
    sampling: "nearest-from-original-concept",
    colors: "exact-source-rgb",
    quadrantSampling: "area-weighted-source-rgb-medoid-with-center-prior-full-canvas-half-width-subpixels",
    quadrantColors: "two-source-rgb-medoids-per-cell",
    quadrantErrorWeights,
    centerPriorWeight,
    flatRegionMaxChannelSpread: 3,
    alphaThreshold,
  },
};
// The generated color tables are data, not handwritten source. Keep them
// compact; the script and the source hash make regeneration reviewable.
writeFileSync(outputPath, `${JSON.stringify(result)}\n`);
console.log(JSON.stringify({ output: outputPath, source: result.source,
  grids: variants.map(({ width, height, palette }) => ({ grid: `${width}x${height}`, colors: palette.length - 1 })) }));

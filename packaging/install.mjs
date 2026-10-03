#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, realpathSync, renameSync, rmSync, symlinkSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const source = dirname(fileURLToPath(import.meta.url));
const hash = data => createHash("sha256").update(data).digest("hex");
const shellQuote = value => "'" + value.replaceAll("'", "'\\''") + "'";
const within = (root, path) => { const r = relative(root, path); return r === "" || (!r.startsWith(`..${sep}`) && r !== ".." && !isAbsolute(r)); };

// Checksums detect corruption; authenticity comes from obtaining the archive from a trusted source.
function verify(root, manifest, manifestBytes) {
  if (!readFileSync(join(root, "bundle.json")).equals(manifestBytes)) throw new Error("Bundle manifest mismatch");
  const observed = new Set();
  function walk(dir) {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name), key = relative(root, path).split(sep).join("/");
      if (key === "bundle.json") continue;
      const info = lstatSync(path);
      if (info.isDirectory()) { walk(path); continue; }
      const expected = manifest.files[key];
      if (!expected) throw new Error(`Unexpected file: ${key}`);
      observed.add(key);
      if (info.isSymbolicLink()) {
        const target = readlinkSync(path);
        if (target !== expected.link || isAbsolute(target) || !within(root, realpathSync(path))) throw new Error(`Invalid link: ${key}`);
      } else if (!info.isFile() || expected.sha256 !== hash(readFileSync(path)) || (info.mode & 0o111) !== expected.executable) {
        throw new Error(`Checksum or mode mismatch: ${key}`);
      }
    }
  }
  walk(root);
  for (const key of Object.keys(manifest.files)) if (!observed.has(key)) throw new Error(`Missing file: ${key}`);
}

function ownedLink(path, target) {
  try {
    const info = lstatSync(path);
    if (!info.isSymbolicLink() || resolve(dirname(path), readlinkSync(path)) !== target) throw new Error(`Refusing to replace another installation: ${path}`);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}

try {
  const args = process.argv.slice(2);
  if (args.includes("--help")) {
    console.log("Usage: sh install.sh [--prefix DIRECTORY] [--bin-dir DIRECTORY]\nDefaults: ~/.local/share/research-cli and ~/.local/bin. No sudo or network required.");
    process.exit(0);
  }
  let prefix = join(homedir(), ".local", "share", "research-cli"), binDir = join(homedir(), ".local", "bin");
  for (let i = 0; i < args.length; i++) {
    const flag = args[i], value = args[++i];
    if (!["--prefix", "--bin-dir"].includes(flag) || !value || value.startsWith("--")) throw new Error("Use --prefix DIRECTORY or --bin-dir DIRECTORY");
    if (flag === "--prefix") prefix = resolve(value); else binDir = resolve(value);
  }
  const manifestBytes = readFileSync(join(source, "bundle.json"));
  const manifest = JSON.parse(manifestBytes);
  if (manifest.format !== 1 || manifest.platform !== `${process.platform}-${process.arch}`) throw new Error(`Wrong installer for ${process.platform}-${process.arch}`);
  verify(source, manifest, manifestBytes);
  mkdirSync(prefix, { recursive: true }); prefix = realpathSync(prefix);
  mkdirSync(binDir, { recursive: true }); binDir = realpathSync(binDir);
  if (within(source, prefix) || within(source, binDir)) throw new Error("Install outside the extracted archive directory");
  const versions = join(prefix, "versions"), current = join(prefix, "current"), command = join(binDir, "research");
  ownedLink(command, join(current, "bin", "research"));
  if (existsSync(current) || (() => { try { return lstatSync(current).isSymbolicLink(); } catch { return false; } })()) {
    if (!lstatSync(current).isSymbolicLink() || !within(versions, resolve(prefix, readlinkSync(current)))) throw new Error("Install prefix belongs to another application");
  }
  mkdirSync(versions, { recursive: true });
  const id = `${manifest.version}-${manifest.platform}-${hash(manifestBytes).slice(0, 12)}`;
  if (!/^[a-zA-Z0-9._-]+$/.test(id)) throw new Error("Invalid bundle identifier");
  const destination = join(versions, id), staging = join(versions, `.install-${randomUUID()}`);
  if (existsSync(destination)) verify(destination, manifest, manifestBytes);
  else {
    try {
      cpSync(source, staging, { recursive: true, verbatimSymlinks: true });
      verify(staging, manifest, manifestBytes);
      const check = spawnSync(join(staging, "bin", "research"), ["doctor"], { encoding: "utf8", timeout: 30000, env: { ...process.env, RESEARCH_SKIP_CONFIG: "1" } });
      if (check.status !== 0) throw new Error("Bundled runtime check failed; previous version remains active.");
      renameSync(staging, destination);
    } finally { rmSync(staging, { recursive: true, force: true }); }
  }
  const pending = join(prefix, `.current-${randomUUID()}`);
  symlinkSync(relative(prefix, destination), pending); renameSync(pending, current);
  if (!existsSync(command)) symlinkSync(join(current, "bin", "research"), command);
  console.log(`Amadeus ${manifest.version} installed.\nCommand: ${command}\nConfigure API: ${shellQuote(command)} configure\nStart: ${shellQuote(command)}`);
  if (!(process.env.PATH || "").split(":").includes(binDir)) console.log(`Add the command directory to PATH: export PATH=${shellQuote(binDir)}:"$PATH"`);
  console.log("Old versions and your API settings/research data are preserved. No shell profile was changed.");
} catch (error) { console.error(`Installation failed: ${error.message}`); process.exitCode = 1; }

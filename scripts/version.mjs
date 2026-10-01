/** Synchronize release metadata without changing dependency resolutions or contacting registries. */
import { readFileSync, writeFileSync, renameSync, rmSync, statSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const files = ["package.json", "package-lock.json", "pyproject.toml", "src/research_cli/__init__.py", "uv.lock", "packaging/download.sh"];
const stableVersion = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
function match(text, expression, file) {
  const result = expression.exec(text);
  if (!result) throw new Error(`Cannot find release version in ${file}`);
  return result;
}
function metadata(root) {
  const contents = Object.fromEntries(files.map(file => [file, readFileSync(join(root, file), "utf8")]));
  const pkg = JSON.parse(contents["package.json"]);
  const npmLock = JSON.parse(contents["package-lock.json"]);
  const project = match(contents["pyproject.toml"], /\[project\]([\s\S]*?)(?=\n\[|$)/, "pyproject.toml")[1];
  const pythonName = match(project, /^name\s*=\s*"([^"]+)"/m, "pyproject.toml")[1];
  const escapedName = pythonName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pythonLock = new RegExp(`(\\[\\[package\\]\\]\\r?\\nname = "${escapedName}"\\r?\\nversion = ")([^"]+)(")`);
  const versions = {
    npm: pkg.version,
    npmLock: npmLock.version,
    npmLockPackage: npmLock.packages?.[""]?.version,
    python: match(project, /^version\s*=\s*"([^"]+)"/m, "pyproject.toml")[1],
    pythonModule: match(contents["src/research_cli/__init__.py"], /^__version__\s*=\s*"([^"]+)"/m, "__init__.py")[1],
    pythonLock: match(contents["uv.lock"], pythonLock, "uv.lock")[2],
    installer: match(contents["packaging/download.sh"], /^VERSION=['"]?([0-9.]+)['"]?$/m, "download.sh")[1],
  };
  return { contents, versions, pkg, npmLock, pythonLock };
}
export function checkVersions(root) {
  const { versions } = metadata(root);
  if (!stableVersion.test(versions.npm) || Object.values(versions).some(version => version !== versions.npm)) throw new Error("Release versions disagree: " + JSON.stringify(versions));
  return versions.npm;
}
export function syncVersion(root, version) {
  if (!stableVersion.test(version)) throw new Error("Use a stable semantic version such as 0.3.0");
  const { contents, npmLock, pythonLock } = metadata(root);
  npmLock.version = version;
  npmLock.packages[""].version = version;
  const updated = {
    "package.json": contents["package.json"].replace(/(^\s*"version"\s*:\s*")[^"]+("\s*,?)/m, (_all, before, after) => before + version + after),
    "package-lock.json": JSON.stringify(npmLock, null, 2) + "\n",
    "pyproject.toml": contents["pyproject.toml"].replace(/(\[project\][\s\S]*?\nversion\s*=\s*")[^"]+("\s*\n)/, (_all, before, after) => before + version + after),
    "src/research_cli/__init__.py": contents["src/research_cli/__init__.py"].replace(/(^__version__\s*=\s*")[^"]+(")/m, (_all, before, after) => before + version + after),
    "uv.lock": contents["uv.lock"].replace(pythonLock, (_all, before, _old, after) => before + version + after),
    "packaging/download.sh": contents["packaging/download.sh"].replace(/^VERSION=['"]?[0-9.]+['"]?$/m, `VERSION=${version}`),
  };
  const staged = [];
  try {
    for (const file of files) {
      const path = join(root, file), temporary = `${path}.${randomUUID()}.tmp`;
      writeFileSync(temporary, updated[file], { mode: statSync(path).mode });
      staged.push([file, temporary, path]);
    }
    for (const [_file, temporary, path] of staged) renameSync(temporary, path);
    return checkVersions(root);
  } catch (error) {
    // Restore metadata if any write failed; dependency content always remains unchanged.
    for (const [file, _temporary, path] of staged) {
      try { writeFileSync(path, contents[file]); } catch { /* preserve original error */ }
    }
    throw error;
  } finally { for (const [_file, temporary] of staged) rmSync(temporary, { force: true }); }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  try {
    const args = process.argv.slice(2);
    if (args.length !== 1) throw new Error("Usage: node scripts/version.mjs --check | VERSION");
    const version = args[0] === "--check" ? checkVersions(root) : syncVersion(root, args[0]);
    console.log(`Research CLI versions synchronized: ${version}`);
  } catch (error) { console.error(error.message); process.exitCode = 2; }
}

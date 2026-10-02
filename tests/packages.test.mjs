import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { builtinPackages, handlePackageCommand, loadPackageSelection, normalizePackageSource, packagePaths, readPackageManifest } from "../bin/packages.mjs";

function fixture() {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "research-packages-")));
  const env = { XDG_CONFIG_HOME: join(root, "config"), XDG_DATA_HOME: join(root, "data") };
  const pkg = join(root, "extension"), policy = join(root, "policy.json");
  mkdirSync(pkg);
  writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "fixture-extension", version: "1.0.0", pi: { extensions: ["extension.mjs"] } }));
  writeFileSync(join(pkg, "extension.mjs"), "export default () => {};\n");
  writeFileSync(policy, JSON.stringify({ extensions: ["extension.mjs"], effects: { fixture_lookup: "read" } }));
  const output = [];
  const options = { root, cwd: root, env, output: text => output.push(text) };
  return { root, env, pkg, policy, output, options, close: () => rmSync(root, { recursive: true, force: true }) };
}

test("package sources require exact versions, commit hashes or selected local directories", () => {
  const f = fixture();
  try {
    assert.equal(normalizePackageSource("npm:@scope/package@1.2.3"), "npm:@scope/package@1.2.3");
    const git = "git:https://github.com/owner/repo@" + "a".repeat(40);
    assert.equal(normalizePackageSource(git), git);
    assert.equal(normalizePackageSource("./extension", f.root, true), f.pkg);
    for (const source of ["npm:package", "npm:package@latest", "npm:package@^1.2.3", "git:https://github.com/owner/repo@main", "package", "npm:../private@1.0.0"]) assert.throws(() => normalizePackageSource(source, f.root));
  } finally { f.close(); }
});

test("public Pi manager installs a selected local package disabled until a policy is provided", async () => {
  const f = fixture();
  try {
    assert.equal(await handlePackageCommand(["doctor"], f.options), undefined);
    assert.equal(await handlePackageCommand(["packages", "install", "./extension"], f.options), 0);
    const file = packagePaths(f.env).configFile;
    assert.equal(statSync(file).mode & 0o777, 0o600);
    assert.equal(readPackageManifest(file).packages[0].enabled, false);
    assert.equal(existsSync(join(f.root, ".pi")), false);
    const disabled = await loadPackageSelection({ ...f.options, includeBuiltin: false });
    assert.deepEqual(disabled.extensions, []);
    await handlePackageCommand(["packages", "list"], f.options);
    assert.equal(JSON.parse(f.output.at(-1)).user[0].status, "installed-disabled");
    await handlePackageCommand(["packages", "install", "./extension", "--policy", f.policy], f.options);
    const selection = await loadPackageSelection({ ...f.options, includeBuiltin: false });
    assert.equal(selection.extensions[0].path, join(f.pkg, "extension.mjs"));
    assert.deepEqual(selection.policies.fixture_lookup, { effect: "read", source: f.pkg, network: true });
    assert.equal(readPackageManifest(file).packages.length, 1);
    await handlePackageCommand(["packages", "remove", "./extension"], f.options);
    assert.deepEqual(readPackageManifest(file).packages, []);
    assert.equal(existsSync(f.pkg), true, "Pi preserves the local package source directory");
  } finally { f.close(); }
});

test("package policy rejects wildcard tools, reserved names and broad resource patterns", async () => {
  const f = fixture();
  try {
    for (const invalid of [
      { extensions: ["extension.mjs"], effects: { "*": "read" } },
      { extensions: ["extension.mjs"], effects: { read: "read" } },
      { extensions: ["extension.mjs"], effects: { agent_tasks: "read" } },
      { extensions: ["extension.mjs"], effects: { mcp__research__save_evidence: "read" } },
      { extensions: ["extension.mjs"], effects: { fixture: "unknown" } },
      { extensions: ["../outside.mjs"], effects: { fixture: "read" } },
      { extensions: ["extensions/*.ts"], effects: { fixture: "read" } },
      { extensions: ["extension.mjs"], effects: {} },
      { extensions: ["extension.mjs"], effects: { fixture: "read" }, networkTools: ["other"] },
    ]) {
      writeFileSync(f.policy, JSON.stringify(invalid));
      await assert.rejects(() => handlePackageCommand(["packages", "install", "./extension", "--policy", f.policy], f.options));
      assert.equal(existsSync(packagePaths(f.env).configFile), false);
    }
  } finally { f.close(); }
});

test("startup reports missing resources and cannot follow a resource symlink out of the package", async () => {
  const f = fixture();
  try {
    await handlePackageCommand(["packages", "install", "./extension", "--policy", f.policy], f.options);
    rmSync(join(f.pkg, "extension.mjs"));
    await assert.rejects(() => loadPackageSelection({ ...f.options, includeBuiltin: false }), /missing/);
    const outside = join(f.root, "outside.mjs");
    writeFileSync(outside, "export default () => {};\n");
    symlinkSync(outside, join(f.pkg, "extension.mjs"));
    await assert.rejects(() => loadPackageSelection({ ...f.options, includeBuiltin: false }), /outside/);
  } finally { f.close(); }
});

test("startup never installs a missing npm package and reports the exact requested version", async () => {
  const f = fixture();
  const paths = packagePaths(f.env);
  try {
    mkdirSync(join(paths.configFile, ".."), { recursive: true });
    writeFileSync(paths.configFile, JSON.stringify({ version: 1, packages: [{ source: "npm:research-nonexistent-fixture@1.2.3", extensions: ["extension.mjs"], effects: { fixture_lookup: "read" } }] }));
    await assert.rejects(() => loadPackageSelection({ ...f.options, includeBuiltin: false }), /not installed at the selected version/);
    assert.equal(existsSync(paths.agentDir), false);
    assert.equal(JSON.parse(readFileSync(paths.configFile, "utf8")).packages[0].source, "npm:research-nonexistent-fixture@1.2.3");
  } finally { f.close(); }
});

test("startup rejects a cached npm version or Git checkout that differs from its pinned source", async () => {
  const f = fixture();
  const paths = packagePaths(f.env);
  try {
    mkdirSync(join(paths.configFile, ".."), { recursive: true });
    const cachedNpm = join(paths.agentDir, "npm", "node_modules", "fixture-tools");
    mkdirSync(cachedNpm, { recursive: true });
    writeFileSync(join(cachedNpm, "package.json"), JSON.stringify({ name: "fixture-tools", version: "1.2.4", pi: { extensions: ["extension.mjs"] } }));
    writeFileSync(paths.configFile, JSON.stringify({ version: 1, packages: [{ source: "npm:fixture-tools@1.2.3", extensions: ["extension.mjs"], effects: { fixture_lookup: "read" } }] }));
    await assert.rejects(() => loadPackageSelection({ ...f.options, includeBuiltin: false }), /not installed at the selected version/);
    const cachedGit = join(paths.agentDir, "git", "github.com", "owner", "fixture-tools");
    mkdirSync(join(cachedGit, ".git", "objects"), { recursive: true });
    mkdirSync(join(cachedGit, ".git", "refs", "heads"), { recursive: true });
    writeFileSync(join(cachedGit, ".git", "HEAD"), "ref: refs/heads/main\n");
    writeFileSync(join(cachedGit, ".git", "config"), "[core]\nrepositoryformatversion=0\nbare=false\n");
    writeFileSync(join(cachedGit, ".git", "refs", "heads", "main"), "a".repeat(40) + "\n");
    writeFileSync(join(cachedGit, "package.json"), JSON.stringify({ name: "fixture-tools", version: "1.2.3", pi: { extensions: ["extension.mjs"] } }));
    writeFileSync(join(cachedGit, "extension.mjs"), "export default () => {};\n");
    const document = { version: 1, packages: [{ source: "git:https://github.com/owner/fixture-tools@" + "b".repeat(40), extensions: ["extension.mjs"], effects: { fixture_lookup: "read" } }] };
    writeFileSync(paths.configFile, JSON.stringify(document));
    await assert.rejects(() => loadPackageSelection({ ...f.options, includeBuiltin: false }), /not installed at the selected version/);
    document.packages[0].source = "git:https://github.com/owner/fixture-tools@" + "a".repeat(40);
    writeFileSync(paths.configFile, JSON.stringify(document));
    assert.equal((await loadPackageSelection({ ...f.options, includeBuiltin: false })).extensions.length, 1);
  } finally { f.close(); }
});

test("bundled package resources use their exact dependency versions and independent tool policies", async () => {
  const f = fixture();
  try {
    for (const entry of builtinPackages) {
      const directory = join(f.root, "node_modules", entry.name);
      mkdirSync(directory, { recursive: true });
      writeFileSync(join(directory, "package.json"), JSON.stringify({ name: entry.name, version: entry.version, pi: { extensions: entry.extensions } }));
      for (const resource of entry.extensions) { mkdirSync(join(directory, resource, ".."), { recursive: true }); writeFileSync(join(directory, resource), "export default () => {};\n"); }
    }
    const selection = await loadPackageSelection(f.options);
    assert.equal(selection.extensions.length, 2);
    assert.equal(selection.policies.web_search.effect, "external");
    assert.equal(selection.policies.get_search_content.network, false);
    assert.equal(selection.policies["query-docs"].network, true);
    assert.equal(selection.extensions.some(entry => entry.source.includes("pi-docparser")), false);
    await handlePackageCommand(["packages", "list"], f.options);
    const bundled = JSON.parse(f.output.at(-1)).bundled;
    assert.equal(bundled.find(item => item.source === "npm:pi-docparser@4.0.0").status, "parser-engine");
    assert.equal(bundled.find(item => item.source === "npm:pi-subagents@0.74.0").status, "delegation-engine");
    await assert.rejects(() => handlePackageCommand(["packages", "remove", "npm:pi-web-access@0.35.0"], f.options), /Bundled packages/);
  } finally { f.close(); }
});

test("explicit project package manifests are selected without reading ambient Pi settings", async () => {
  const f = fixture();
  try {
    const file = join(f.root, "selected.json");
    writeFileSync(file, JSON.stringify({ version: 1, packages: [{ source: "./extension", extensions: ["extension.mjs"], effects: { fixture_lookup: "read" }, networkTools: [] }] }));
    mkdirSync(join(f.root, ".pi"));
    writeFileSync(join(f.root, ".pi", "settings.json"), JSON.stringify({ packages: ["npm:must-not-install@9.9.9"] }));
    const selection = await loadPackageSelection({ ...f.options, file, includeBuiltin: false });
    assert.equal(selection.extensions.length, 1);
    assert.equal(selection.policies.fixture_lookup.network, false);
    assert.equal(existsSync(packagePaths(f.env).agentDir), false);
    writeFileSync(file, JSON.stringify({ version: 1, packages: [{ source: f.pkg, extensions: ["extension.mjs"], effects: { fixture: "read" } }, { source: f.pkg, enabled: false }] }));
    assert.throws(() => readPackageManifest(file), /Duplicate/);
  } finally { f.close(); }
});

test("Pi manager delegates npm installation with lifecycle scripts disabled into the independent directory", async () => {
  const f = fixture();
  try {
    const bundle = join(f.root, "bundle"), npm = join(bundle, "runtime", "node", "bin", "npm"), log = join(f.root, "npm-args.jsonl");
    mkdirSync(join(npm, ".."), { recursive: true });
    writeFileSync(npm, `#!${process.execPath}\nconst fs = require('node:fs'), path = require('node:path');\nconst args = process.argv.slice(2);\nfs.appendFileSync(${JSON.stringify(log)}, JSON.stringify(args) + '\\n');\nif (args.includes('install')) {\n const prefix = args[args.indexOf('--prefix') + 1];\n const spec = args[args.indexOf('install') + 1];\n const split = spec.lastIndexOf('@'), name = spec.slice(0, split), version = spec.slice(split + 1);\n const directory = path.join(prefix, 'node_modules', name);\n fs.mkdirSync(directory, {recursive:true});\n fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({name,version,pi:{extensions:['extension.mjs']}}));\n fs.writeFileSync(path.join(directory, 'extension.mjs'), 'export default () => {};');\n}\n`, { mode: 0o700 });
    f.env.RESEARCH_BUNDLE_ROOT = bundle;
    await handlePackageCommand(["packages", "install", "npm:fixture-tools@1.2.3", "--policy", f.policy], f.options);
    const rows = readFileSync(log, "utf8").trim().split("\n").map(row => JSON.parse(row));
    const installation = rows.find(args => args.includes("install"));
    assert.equal(installation[0], "--ignore-scripts");
    assert.equal(installation[installation.indexOf("--prefix") + 1], join(packagePaths(f.env).agentDir, "npm"));
    const selection = await loadPackageSelection({ ...f.options, includeBuiltin: false });
    assert.equal(selection.extensions.length, 1);
    assert.equal(selection.extensions[0].source, "npm:fixture-tools@1.2.3");
    assert.equal(rows.length, 1, "Startup resolution makes no npm call when the selected version is installed");
    assert.equal(existsSync(join(f.root, ".pi")), false);
  } finally { f.close(); }
});

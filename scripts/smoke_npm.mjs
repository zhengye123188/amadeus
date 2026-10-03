/** Install the actual npm tarball into a temporary prefix, then bootstrap its Python service. */
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, readFileSync, realpathSync } from "node:fs";
import { createInterface } from "node:readline";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const temp = mkdtempSync(join(tmpdir(), "research-npm-install-"));
const tarball = resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("Pass the npm .tgz path");
const expectedVersion = JSON.parse(readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8")).version;
const env = { ...process.env, RESEARCH_SKIP_CONFIG: "1", XDG_CACHE_HOME: join(temp, "cache"), XDG_CONFIG_HOME: join(temp, "config"), XDG_DATA_HOME: join(temp, "data") };
delete env.RESEARCH_PYTHON;
function run(cmd, args, cwd = temp) {
  const r = spawnSync(cmd, args, { cwd, env, encoding: "utf8", timeout: 180000 });
  if (r.status !== 0) throw new Error(`${cmd}: ${r.error?.message || r.stderr || r.stdout}`);
  return r.stdout;
}
try {
  run("npm", ["install", "--prefix", temp, "--ignore-scripts", "--no-audit", "--no-fund", tarball]);
  const executable = join(temp, "node_modules", ".bin", "research");
  const version = run(executable, ["--version"]);
  if (!version.startsWith(expectedVersion + " ")) throw new Error("Installed CLI version mismatch");
  const packages = JSON.parse(run(executable, ["packages", "list"]));
  if (packages.bundled.length !== 4 || packages.bundled.some(item => item.status === "bundled-missing")) throw new Error("Bundled Pi packages are missing from the installed tarball");
  run(executable, ["setup"]);
  const doctor = JSON.parse(run(executable, ["doctor"]));
  if (doctor.backend !== expectedVersion || !doctor.python.startsWith(temp)) throw new Error("Backend did not install in the isolated cache");
  const workspace = join(temp, "work"); mkdirSync(workspace);
  const installedRoot = dirname(dirname(realpathSync(executable)));
  env.RESEARCH_NODE = process.execPath;
  env.RESEARCH_DOCUMENT_PARSER = join(installedRoot, "bin", "document-parser.mjs");
  const parsed = JSON.parse(run(doctor.python, ["-c", `
import asyncio, json
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from research_cli.config import Settings
from research_cli.storage import Store
from research_cli.tools import Registry
from research_cli.research import ResearchTools
writer=PdfWriter()
writer.add_blank_page(width=300,height=200)
page=writer.add_blank_page(width=300,height=200)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
stream=DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 20 150 Td (Installed parser source on page two.) Tj ET')
page[NameObject('/Contents')]=writer._add_object(stream)
writer.write('source.pdf')
async def main():
    store=Store(Path.cwd())
    tools=ResearchTools(Registry(store,Settings(permission='workspace-write',allow_network=False)))
    try:
        result=await tools.import_document({'path':'source.pdf'})
        chunks=[{'position':json.loads(row[0]),'text':row[1]} for row in store.db.execute('SELECT position,text FROM chunks')]
        print(json.dumps({'source':result,'chunks':chunks}))
    finally:
        await tools.close()
        store.close()
asyncio.run(main())
`], workspace));
  if (parsed.source.pages !== 2 || parsed.source.provenance.extraction.parser !== "pi-docparser" || parsed.source.provenance.extraction.version !== "4.0.0" || parsed.chunks[0]?.position.page !== 2 || !parsed.chunks[0]?.text.includes("Installed parser source")) throw new Error("Installed PDF importer did not retain extraction provenance and blank page positions");
  run(doctor.python, ["-m", "research_cli.mcp_server", "--version"]);
  await new Promise((resolve, reject) => {
    const child = spawn(executable, ["--workspace", workspace, "--offline", "--mode", "rpc"], {
      cwd: temp, env: { ...env, PI_CODING_AGENT_DIR: join(temp, "agent"), PI_OFFLINE: "1", PI_TELEMETRY: "0", OPENAI_API_KEY: "fixture-not-used", OPENAI_BASE_URL: "http://127.0.0.1:1/v1", RESEARCH_MODEL: "fixture" },
    });
    let checked = false, stderr = "";
    const timer = setTimeout(() => { child.kill("SIGTERM"); reject(new Error(`Installed Pi startup timed out: ${stderr}`)); }, 20000);
    child.stderr.on("data", data => { stderr += data; });
    createInterface({ input: child.stdout }).on("line", line => {
      let event; try { event = JSON.parse(line); } catch { return; }
      if (event.type === "response" && event.id === "commands") {
        checked = event.success && event.data.commands.some(command => command.name === "research-status");
        child.stdin.end();
      }
    });
    child.on("error", error => { clearTimeout(timer); reject(error); });
    child.on("exit", code => { clearTimeout(timer); checked && code === 0 ? resolve() : reject(new Error(`Installed Pi extension failed: ${stderr}`)); });
    child.stdin.write(JSON.stringify({ id: "commands", type: "get_commands" }) + "\n");
  });
  // Drive the installed executable through a real PTY, using the checkout's test
  // Python only as the fixture driver; the CLI uses its isolated installed backend.
  const terminal = JSON.parse(run(resolve(".venv/bin/python"), [
    fileURLToPath(new URL("./smoke_ui.py", import.meta.url)),
    "--cli", executable, "--python", doctor.python, "--node", process.execPath,
  ]));
  if (!terminal.real_terminal || !terminal.pixel_header) throw new Error("Installed terminal UI did not pass the PTY check");
  console.log(JSON.stringify({ npm_cli: "installed tarball", version: version.trim(), backend: doctor.backend, isolated_cache: true, real_pi_extension_loaded: true, bundled_packages: packages.bundled.map(item => item.source), native_pdf_import: true, interactive_terminal: terminal }));
} finally { rmSync(temp, { recursive: true, force: true }); }

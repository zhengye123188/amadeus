/** Install the actual npm tarball into a temporary prefix, then bootstrap its Python service. */
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { createInterface } from "node:readline";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const temp = mkdtempSync(join(tmpdir(), "research-npm-install-"));
const tarball = resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("Pass the npm .tgz path");
const env = { ...process.env, RESEARCH_SKIP_CONFIG: "1", XDG_CACHE_HOME: join(temp, "cache") };
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
  if (!version.startsWith("0.2.0")) throw new Error("Installed CLI version mismatch");
  run(executable, ["setup"]);
  const doctor = JSON.parse(run(executable, ["doctor"]));
  if (doctor.backend !== "0.2.0" || !doctor.python.startsWith(temp)) throw new Error("Backend did not install in the isolated cache");
  const workspace = join(temp, "work"); mkdirSync(workspace);
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
  console.log(JSON.stringify({ npm_cli: "installed tarball", version: version.trim(), backend: doctor.backend, isolated_cache: true, real_pi_extension_loaded: true }));
} finally { rmSync(temp, { recursive: true, force: true }); }

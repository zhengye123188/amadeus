import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createServer } from "node:http";
import { createInterface } from "node:readline";
import { resolve } from "node:path";
import type { AddressInfo } from "node:net";

export type Reply = { text: string } | { tool: string; args: Record<string, unknown> };
export type Request = { messages: Array<{ role: string; content: unknown; tool_calls?: unknown[] }>; tools?: Array<{function: {name: string}}> };
export async function mockEndpoint(respond: (request: Request) => Reply | Promise<Reply>, expectedApiKey = "local-test-only") {
  const requests: Request[] = [];
  let rejectedAuth = 0;
  const server = createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    // Exercise the real HTTP auth boundary without retaining or logging credentials.
    if (req.headers.authorization !== `Bearer ${expectedApiKey}`) {
      rejectedAuth++;
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { message: "Fixture rejected Authorization header", type: "authentication_error" } }));
      return;
    }
    try {
      const body = JSON.parse(raw) as Request;
      requests.push(body);
      const reply = await respond(body);
      const delta = "tool" in reply
        ? { role: "assistant", tool_calls: [{ index: 0, id: `call_${requests.length}`, type: "function", function: { name: reply.tool, arguments: JSON.stringify(reply.args) } }] }
        : { role: "assistant", content: reply.text };
      const chunk = (delta: unknown, reason: string | null) => ({ id: `chatcmpl-${requests.length}`, object: "chat.completion.chunk", created: Math.floor(Date.now()/1000), model: "fixture", choices: [{ index: 0, delta, finish_reason: reason }] });
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.write(`data: ${JSON.stringify(chunk(delta, null))}\n\n`);
      res.write(`data: ${JSON.stringify({ ...chunk({}, "tool" in reply ? "tool_calls" : "stop"), usage: { prompt_tokens: 200, completion_tokens: 30, total_tokens: 230 } })}\n\n`);
      res.end("data: [DONE]\n\n");
    } catch (e) { res.writeHead(500); res.end(String(e)); }
  });
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
  return { url, requests, authFailures: () => rejectedAuth, close: () => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }) };
}

export class ResearchProcess {
  child: ChildProcessWithoutNullStreams;
  events: any[] = [];
  stderr = "";
  private sequence = 0;
  private listeners = new Set<() => void>();
  constructor(workspace: string, agentDir: string, endpoint: string, args: string[] = [], env: Record<string, string> = {}) {
    this.child = spawn(process.execPath, [resolve("bin/research.mjs"), "--workspace", workspace, "--mode", "rpc", "--permission", "workspace-write", "--offline", ...args], {
      cwd: process.cwd(), env: { ...process.env, PI_CODING_AGENT_DIR: agentDir, PI_OFFLINE: "1", PI_TELEMETRY: "0",
        RESEARCH_PYTHON: process.env.RESEARCH_PYTHON || resolve(".venv/bin/python"), OPENAI_BASE_URL: endpoint, OPENAI_API_KEY: "local-test-only", RESEARCH_MODEL: "fixture", RESEARCH_API: "chat", ...env },
    });
    createInterface({ input: this.child.stdout }).on("line", line => {
      try { this.events.push(JSON.parse(line)); } catch { this.stderr += line + "\n"; }
      for (const listener of this.listeners) listener();
    });
    this.child.stderr.on("data", data => { this.stderr += data; });
    this.child.on("exit", () => { for (const listener of this.listeners) listener(); });
  }
  wait(predicate: (event: any) => boolean, from = 0, timeout = 30000): Promise<any> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { cleanup(); reject(new Error(`Timed out waiting for Pi. stderr=${this.stderr}\nevents=${JSON.stringify(this.events.slice(-5))}`)); }, timeout);
      const cleanup = () => { clearTimeout(timer); this.listeners.delete(check); };
      const check = () => {
        const event = this.events.slice(from).find(predicate);
        if (event) { cleanup(); resolve(event); }
        else if (this.child.exitCode !== null) { cleanup(); reject(new Error(`Pi exited ${this.child.exitCode}: ${this.stderr}`)); }
      };
      this.listeners.add(check); check();
    });
  }
  async command(type: string, body: Record<string, unknown> = {}) {
    const id = `req-${++this.sequence}`;
    const response = this.wait(event => event.type === "response" && event.id === id);
    this.child.stdin.write(JSON.stringify({ id, type, ...body }) + "\n");
    const result = await response;
    if (!result.success) throw new Error(`${type}: ${result.error}`);
    return result.data;
  }
  async prompt(message: string) {
    const from = this.events.length;
    const settled = this.wait(event => event.type === "agent_settled", from);
    await this.command("prompt", { message });
    await settled;
    return this.events.slice(from);
  }
  async close() {
    if (this.child.exitCode !== null) return;
    this.child.stdin.end();
    await new Promise<void>(resolve => {
      const timer = setTimeout(() => this.child.kill("SIGTERM"), 5000);
      this.child.once("exit", () => { clearTimeout(timer); resolve(); });
    });
  }
}

export function toolResults(request: Request): any[] {
  return request.messages.filter(message => message.role === "tool").map(message => {
    let text = typeof message.content === "string" ? message.content : JSON.stringify(message.content);
    try { return JSON.parse(text); } catch { return { raw: text }; }
  });
}

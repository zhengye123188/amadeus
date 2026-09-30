import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, linkSync, rmSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { approvalToken, autoApprove, safePath } from "../../pi/policy.ts";

test("workspace policy covers paths, symlinks, hard links and credential files", () => {
  const root = mkdtempSync(join(tmpdir(), "research-policy-"));
  try {
    mkdirSync(join(root, "workspace"));
    const ws = join(root, "workspace");
    writeFileSync(join(root, "outside.txt"), "outside");
    writeFileSync(join(ws, "inside.txt"), "inside");
    symlinkSync(root, join(ws, "escape"));
    linkSync(join(ws, "inside.txt"), join(ws, "hard.txt"));
    assert.equal(safePath(ws, "nested/new.txt", true), join(realpathSync(ws), "nested/new.txt"));
    assert.throws(() => safePath(ws, "../outside.txt"), /outside/);
    assert.throws(() => safePath(ws, "escape/outside.txt"), /Symlink/);
    assert.throws(() => safePath(ws, ".env"), /blocked/);
    assert.throws(() => safePath(ws, ".pi/auth.json"), /blocked/);
    assert.throws(() => safePath(ws, "hard.txt", true), /hard-linked/);
    assert.throws(() => safePath(ws, "."), /regular files/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("read-only wins over experiment opt-in; tokens bind full arguments", () => {
  assert.equal(autoApprove("execute", "read-only", true), false);
  assert.equal(autoApprove("execute", "ask", false), false);
  assert.equal(autoApprove("execute", "ask", true), true);
  assert.equal(autoApprove("external", "workspace-write", true), false);
  const token = approvalToken("secret", "remember_research", { text: "CPU only" });
  const payload = JSON.parse(Buffer.from(token.split(".")[0], "base64url").toString());
  assert.equal(payload.arguments.text, "CPU only");
  assert.equal(payload.name, "remember_research");
});

test("saved API credentials remain protected inside the workspace", () => {
  const root = mkdtempSync(join(tmpdir(), "research-credential-policy-"));
  const previous = process.env.XDG_CONFIG_HOME;
  try {
    process.env.XDG_CONFIG_HOME = join(root, "config");
    mkdirSync(join(root, "config/research-cli"), { recursive: true });
    writeFileSync(join(root, "config/research-cli/api.json"), "fixture");
    symlinkSync(join(root, "config/research-cli/api.json"), join(root, "alias.json"));
    assert.throws(() => safePath(root, "config/research-cli/api.json"), /credentials/);
    assert.throws(() => safePath(root, "alias.json"), /credentials/);
  } finally {
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

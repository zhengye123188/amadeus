import { lstatSync, readFileSync, readdirSync, realpathSync, statSync } from "node:fs";
import { join } from "node:path";

export function selectedInstructions(file: string | undefined): string | undefined {
  if (!file) return undefined;
  if (!statSync(file).isFile() || statSync(file).size > 32000) throw new Error("Selected project instructions must be a regular text file up to 32 KB");
  const data = readFileSync(file);
  if (data.includes(0)) throw new Error("Selected project instructions must be text");
  return data.toString("utf8");
}

/** Only exact user-selected skill files become readable outside the workspace. */
export function selectedSkillFiles(serialized: string | undefined): Set<string> {
  const paths: unknown = JSON.parse(serialized || "[]");
  if (!Array.isArray(paths) || paths.length > 50 || paths.some(path => typeof path !== "string")) throw new Error("Invalid selected skill paths");
  const files = new Set<string>();
  let scanned = 0;
  const visit = (path: string): void => {
    if (++scanned > 1000) throw new Error("Selected skills exceed 1000 directory entries");
    const info = lstatSync(path);
    if (info.isSymbolicLink()) throw new Error("Selected skills may not contain symlinks");
    if (info.isDirectory()) {
      for (const entry of readdirSync(path)) if (!entry.startsWith(".")) visit(join(path, entry));
    } else if (info.isFile() && (path.endsWith("SKILL.md") || paths.includes(path))) files.add(realpathSync(path));
  };
  for (const path of paths as string[]) visit(path);
  return files;
}

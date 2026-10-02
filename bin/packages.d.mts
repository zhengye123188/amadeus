export type PackageEffect = "read" | "write" | "execute" | "external";
export interface PackagePolicy { effect: PackageEffect; source: string; network: boolean }
export interface SelectedPackageExtension {
  path: string;
  source: string;
  effects: Record<string, PackageEffect>;
  networkTools: string[];
}
export interface PackageSelection {
  extensions: SelectedPackageExtension[];
  skills: string[];
  policies: Record<string, PackagePolicy>;
  disabledResearchTools: string[];
  agentDir: string;
  configFile: string;
}
export function packagePaths(env?: NodeJS.ProcessEnv): { configFile: string; agentDir: string };
export function loadPackageSelection(options: { file?: string; cwd?: string; root: string; env?: NodeJS.ProcessEnv; includeBuiltin?: boolean }): Promise<PackageSelection>;
export function handlePackageCommand(args: string[], options: { cwd?: string; root: string; env?: NodeJS.ProcessEnv; output?: (message: string) => void }): Promise<number | undefined>;
export function packageModuleAliases(): Record<string, string>;

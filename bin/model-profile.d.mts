export interface ModelProfile {
  model?: string;
  contextWindow: number;
  maxTokens: number;
  reasoning: boolean;
  input: ("text" | "image")[];
  prices: Record<"input" | "output" | "cacheRead" | "cacheWrite", number | null>;
  pricingKnown: boolean;
}
export function loadModelProfile(env?: NodeJS.ProcessEnv): ModelProfile;
export function estimateUsageCost(profile: ModelProfile, usage: Partial<Record<"input" | "output" | "cacheRead" | "cacheWrite", number>>): number | null;

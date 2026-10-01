import { readFileSync } from "node:fs";

const priceNames = ["input", "output", "cacheRead", "cacheWrite"];
const priceEnv = { input: "RESEARCH_INPUT_PRICE", output: "RESEARCH_OUTPUT_PRICE", cacheRead: "RESEARCH_CACHE_READ_PRICE", cacheWrite: "RESEARCH_CACHE_WRITE_PRICE" };
function number(value, name, minimum, maximum, integer = false) {
  const result = typeof value === "number" || typeof value === "string" && value.trim() ? Number(value) : NaN;
  if (!Number.isFinite(result) || result < minimum || result > maximum || integer && !Number.isInteger(result)) throw new Error(`Invalid ${name}`);
  return result;
}
function boolean(value, name) {
  if (value === true || value === "true" || value === "1") return true;
  if (value === false || value === "false" || value === "0") return false;
  throw new Error(`Invalid ${name}; use true or false`);
}
/** Prices are USD per million tokens; null means unknown, including unknown cache pricing. */
export function loadModelProfile(env = process.env) {
  let saved = {};
  if (env.RESEARCH_MODEL_PROFILE) {
    try {
      const text = readFileSync(env.RESEARCH_MODEL_PROFILE, "utf8");
      if (text.length > 65536) throw new Error();
      saved = JSON.parse(text);
      if (!saved || typeof saved !== "object" || Array.isArray(saved) || Object.keys(saved).some(key => !["model", "contextWindow", "maxTokens", "reasoning", "input", "prices"].includes(key))) throw new Error();
    } catch { throw new Error("Invalid model profile file; expected a small JSON object with documented model fields."); }
  }
  const contextWindow = number(env.RESEARCH_CONTEXT_WINDOW ?? saved.contextWindow ?? 32768, "RESEARCH_CONTEXT_WINDOW", 8192, 2000000, true);
  const maxTokens = number(env.RESEARCH_MAX_OUTPUT_TOKENS ?? saved.maxTokens ?? 4096, "RESEARCH_MAX_OUTPUT_TOKENS", 1, contextWindow, true);
  const reasoning = boolean(env.RESEARCH_REASONING ?? saved.reasoning ?? false, "RESEARCH_REASONING");
  const input = env.RESEARCH_INPUT ? env.RESEARCH_INPUT.split(",").map(value => value.trim()) : saved.input ?? ["text"];
  if (!Array.isArray(input) || !input.includes("text") || input.some(value => !["text", "image"].includes(value)) || new Set(input).size !== input.length) throw new Error("Invalid model input; use text or text,image");
  if (saved.prices !== undefined && (!saved.prices || typeof saved.prices !== "object" || Array.isArray(saved.prices) || Object.keys(saved.prices).some(key => !priceNames.includes(key)))) throw new Error("Invalid profile prices");
  const prices = Object.fromEntries(priceNames.map(key => {
    const value = env[priceEnv[key]] ?? saved.prices?.[key] ?? null;
    return [key, value === null ? null : number(value, priceEnv[key], 0, 100000)];
  }));
  const model = env.RESEARCH_MODEL ?? saved.model;
  if (model !== undefined && (typeof model !== "string" || !model.trim() || /[\r\n]/.test(model))) throw new Error("Invalid model ID");
  return { ...(model ? { model } : {}), contextWindow, maxTokens, reasoning, input, prices, pricingKnown: priceNames.every(key => prices[key] !== null) };
}

/** Never turn unknown prices into a free estimate. All usage categories are independent. */
export function estimateUsageCost(profile, usage) {
  let total = 0;
  for (const name of priceNames) {
    const tokens = usage[name] ?? 0;
    if (!Number.isFinite(tokens) || tokens < 0) return null;
    if (tokens && profile.prices[name] === null) return null;
    total += tokens * (profile.prices[name] ?? 0) / 1000000;
  }
  return total;
}

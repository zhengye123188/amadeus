/** A /models GET checks endpoint access without generating text or incurring a model completion. */
export async function checkApi(env = process.env, fetchImpl = fetch, timeoutMs = 10000) {
  if (!env.OPENAI_BASE_URL || !env.OPENAI_API_KEY) return { status: "skipped", message: "OPENAI_BASE_URL and OPENAI_API_KEY are required for this check." };
  let url;
  try {
    url = new URL(env.OPENAI_BASE_URL);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || /[\r\n]/.test(env.OPENAI_API_KEY)) throw new Error();
    url.pathname = url.pathname.replace(/\/$/, "") + "/models";
  } catch { return { status: "failed", reason: "invalid_configuration", message: "Use a plain http(s) base URL and a single-line API key." }; }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, { method: "GET", headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, Accept: "application/json" }, signal: controller.signal, redirect: "manual" });
    if ([401, 403].includes(response.status)) return { status: "failed", reason: "authentication", httpStatus: response.status, message: "Endpoint rejected credentials or account permissions. Check your key and provider account." };
    if ([404, 405].includes(response.status)) return { status: "unsupported", httpStatus: response.status, message: "This endpoint does not offer a /models check. Model generation and credentials remain unverified." };
    if (!response.ok) return { status: "failed", reason: response.status >= 300 && response.status < 400 ? "redirect" : "http_error", httpStatus: response.status, message: "Endpoint did not accept the /models request. Redirects are not followed with credentials." };
    // Do not echo provider error bodies, which can contain credentials. Bound untrusted response size.
    const reader = response.body?.getReader();
    let body = "";
    if (reader) {
      const decoder = new TextDecoder();
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          body += decoder.decode(value, { stream: true });
          if (body.length > 1000000) throw new Error("too_large");
        }
        body += decoder.decode();
      } finally { await reader.cancel().catch(() => {}); }
    }
    let models;
    try { const data = JSON.parse(body); models = Array.isArray(data.data) ? data.data : undefined; } catch { /* availability can still be diagnosed without echoing body */ }
    const modelAvailable = env.RESEARCH_MODEL && models ? models.some(model => model?.id === env.RESEARCH_MODEL) : null;
    return { status: modelAvailable === false ? "failed" : "ok", ...(modelAvailable === false ? { reason: "model_not_listed" } : {}), modelAvailable,
      message: modelAvailable === false ? "Configured model is not listed by this endpoint; verify the model ID. Some providers list only a subset." : "Endpoint accepted /models. Completion, reasoning, image and tool-call support were not tested." };
  } catch {
    return { status: "failed", reason: controller.signal.aborted ? "timeout" : "connection", message: controller.signal.aborted ? "API check timed out." : "API check failed to connect or read the response. Check endpoint and network." };
  } finally { clearTimeout(timer); }
}

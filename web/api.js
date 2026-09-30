// Thin fetch wrappers around the server's /api/* routes. No DOM code here.

async function getJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch (_) {
      // response body wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }
  return resp.json();
}

export function search(query) {
  return getJSON(`/api/search?q=${encodeURIComponent(query)}`);
}

export async function startMatch(seedId) {
  const { job_id } = await getJSON("/api/match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seed_id: seedId }),
  });
  return job_id;
}

export function pollMatch(jobId) {
  return getJSON(`/api/match/${jobId}`);
}

export function previewUrl(trackId) {
  return `/api/preview/${trackId}`;
}

export async function startMixSnippet(aId, bId, style, lengthSeconds) {
  const { job_id, snippet_url } = await getJSON("/api/mix-snippet", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a_id: aId, b_id: bId, style, length_seconds: lengthSeconds }),
  });
  return { jobId: job_id, snippetUrl: snippet_url };
}

export function snippetUrl(snippetId) {
  return `/api/snippet/${snippetId}.mp3`;
}

export function shutdown() {
  return fetch("/api/shutdown", { method: "POST" });
}

// Polls a /api/match/{job_id}-shaped endpoint until status is done/error.
// onProgress(progressText) is called on every tick.
export async function pollUntilDone(jobId, pollFn, onProgress, intervalMs = 1500) {
  for (;;) {
    const state = await pollFn(jobId);
    if (onProgress) onProgress(state.progress || "");
    if (state.status === "done") return state.result;
    if (state.status === "error") throw new Error(state.error || "Job failed");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

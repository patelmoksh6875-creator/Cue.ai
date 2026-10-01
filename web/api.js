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

// Used to detect the server going away (e.g. closed while the page is
// still open) so the UI can show a friendly offline message instead of
// leaving stale content or a browser-native connection-failed page.
export async function isHealthy() {
  try {
    const resp = await fetch("/api/health");
    return resp.ok;
  } catch (_) {
    return false;
  }
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

// "Search Deezer for <term>": pulls extra candidates for an artist/genre
// not in the current pool, scores them against the seed, and returns
// {term, results} once the job completes -- the caller merges `results`
// into its existing pool.
export async function refineMatch(seedId, term, onProgress) {
  const { job_id } = await getJSON("/api/match/refine", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seed_id: seedId, term }),
  });
  return pollUntilDone(job_id, pollMatch, onProgress);
}

export function previewUrl(trackId) {
  return `/api/preview/${trackId}`;
}

// Returns { snippetUrl, warnings, note } either immediately (cache hit,
// job_id is null) or after polling the render job to completion.
export async function getMixSnippet(aId, bId, style, lengthSeconds, onProgress) {
  const { job_id, snippet_url } = await getJSON("/api/mix-snippet", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a_id: aId, b_id: bId, style, length_seconds: lengthSeconds }),
  });
  if (job_id === null) {
    return { snippetUrl: snippet_url, warnings: null, note: null };
  }
  const result = await pollUntilDone(job_id, pollMixSnippet, onProgress);
  return { snippetUrl: result.snippet_url, warnings: result.warnings, note: result.note };
}

export function pollMixSnippet(jobId) {
  return getJSON(`/api/mix-snippet/${jobId}`);
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

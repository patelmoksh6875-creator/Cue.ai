import * as api from "./api.js";
import * as filters from "./filters.js";
import * as ui from "./ui.js";

const RESULT_COUNT = 20; // mirrors config.RESULT_COUNT; server also sends result_count_requested

const els = {
  status: document.getElementById("status"),
  quitBtn: document.getElementById("quit-btn"),
  searchInput: document.getElementById("search-input"),
  searchResults: document.getElementById("search-results"),
  seedCard: document.getElementById("seed-card"),
  findMatchesBtn: document.getElementById("find-matches-btn"),
  matchProgress: document.getElementById("match-progress"),
  filterBar: document.getElementById("filter-bar"),
  filterInput: document.getElementById("filter-input"),
  filterSuggestions: document.getElementById("filter-suggestions"),
  filterChips: document.getElementById("filter-chips"),
  sortSelect: document.getElementById("sort-select"),
  clearFiltersBtn: document.getElementById("clear-filters-btn"),
  resultsNote: document.getElementById("results-note"),
  results: document.getElementById("results"),
  player: document.getElementById("player"),
  offlineOverlay: document.getElementById("offline-overlay"),
};

const state = {
  seed: null,
  seedId: null,
  pool: [], // full RESULT_POOL from the server, grown by "search wider" refine calls
  chips: [], // [{type: "artist"|"genre", value}]
  sortBy: "match_pct",
  activePlayButton: null,
  suggestions: [],
  activeSuggestionIndex: -1,
};

function currentFilterSets() {
  return {
    artists: new Set(state.chips.filter((c) => c.type === "artist").map((c) => c.value)),
    genres: new Set(state.chips.filter((c) => c.type === "genre").map((c) => c.value)),
  };
}

function rerenderResults() {
  const { shown, totalMatchingFilter } = filters.visibleResults(
    state.pool,
    currentFilterSets(),
    state.sortBy,
    RESULT_COUNT
  );
  ui.renderResultsNote(els.resultsNote, shown.length, totalMatchingFilter, RESULT_COUNT);
  ui.renderResults(els.results, shown, {
    onPlayPreview: playPreview,
    onPreviewMix: previewMix,
  });
}

function rerenderFilterBar() {
  els.filterBar.hidden = state.pool.length === 0;
  ui.renderChips(els.filterChips, state.chips, (chip) => {
    state.chips = state.chips.filter((c) => !(c.type === chip.type && c.value === chip.value));
    rerenderFilterBar();
    rerenderResults();
  });
  els.clearFiltersBtn.hidden = state.chips.length === 0;
}

function addChip(type, value) {
  if (state.chips.some((c) => c.type === type && c.value === value)) return;
  state.chips.push({ type, value });
  els.filterInput.value = "";
  closeSuggestions();
  rerenderFilterBar();
  rerenderResults();
}

function closeSuggestions() {
  state.suggestions = [];
  state.activeSuggestionIndex = -1;
  ui.renderSuggestions(els.filterSuggestions, [], -1, () => {});
}

function updateSuggestions() {
  const text = els.filterInput.value;
  const base = filters.buildSuggestions(state.pool, text, currentFilterSets());
  const suggestions = text.trim() && base.length === 0
    ? [{ type: "wider", value: text.trim(), wider: true }]
    : base;
  state.suggestions = suggestions;
  state.activeSuggestionIndex = suggestions.length > 0 ? 0 : -1;
  ui.renderSuggestions(els.filterSuggestions, suggestions, state.activeSuggestionIndex, onPickSuggestion);
}

async function onPickSuggestion(suggestion) {
  if (suggestion.wider) {
    await searchWider(suggestion.value);
    return;
  }
  addChip(suggestion.type, suggestion.value);
}

async function searchWider(term) {
  els.filterInput.disabled = true;
  closeSuggestions();
  try {
    const { results } = await api.refineMatch(state.seedId, term, (progress) => {
      ui.renderProgress(els.matchProgress, progress);
    });
    const existingIds = new Set(state.pool.map((r) => r.id));
    const added = results.filter((r) => !existingIds.has(r.id));
    state.pool = [...state.pool, ...added];
    els.filterInput.value = "";
    if (added.length === 0) {
      els.resultsNote.className = "results-note";
      els.resultsNote.textContent = `No matches found for "${term}" against this seed.`;
      els.resultsNote.hidden = false;
    } else {
      rerenderFilterBar();
      rerenderResults();
    }
  } catch (err) {
    ui.renderError(els.resultsNote, `Search Deezer for "${term}": ${err.message}`);
  } finally {
    ui.renderProgress(els.matchProgress, "");
    els.filterInput.disabled = false;
  }
}

function playPreview(trackId, button) {
  if (state.activePlayButton && state.activePlayButton !== button) {
    state.activePlayButton.textContent = "Play";
  }
  if (els.player.dataset.trackId === String(trackId) && !els.player.paused) {
    els.player.pause();
    button.textContent = "Play";
    state.activePlayButton = null;
    return;
  }
  els.player.src = api.previewUrl(trackId);
  els.player.dataset.trackId = String(trackId);
  els.player.hidden = false;
  els.player.play();
  button.textContent = "Pause";
  state.activePlayButton = button;
}

els.player.addEventListener("ended", () => {
  if (state.activePlayButton) state.activePlayButton.textContent = "Play";
  state.activePlayButton = null;
});

async function previewMix(result, button) {
  const original = button.textContent;
  button.disabled = true;
  try {
    const { snippetUrl, warnings, note } = await api.getMixSnippet(
      state.seedId,
      result.id,
      "blend",
      12,
      (progress) => {
        button.textContent = progress || "Rendering...";
      }
    );
    els.player.src = snippetUrl;
    els.player.hidden = false;
    els.player.play();
    ui.renderMixNote(els.resultsNote, note, warnings);
  } catch (err) {
    ui.renderError(els.resultsNote, `Mix snippet: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

let searchDebounce = null;
els.searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  const query = els.searchInput.value.trim();
  if (query.length < 2) {
    ui.renderSearchResults(els.searchResults, [], () => {});
    return;
  }
  searchDebounce = setTimeout(() => runSearch(query), 300);
});

els.searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    clearTimeout(searchDebounce);
    runSearch(els.searchInput.value.trim());
  }
});

async function runSearch(query) {
  if (!query) return;
  try {
    const results = await api.search(query);
    ui.renderSearchResults(els.searchResults, results, pickSeed);
  } catch (err) {
    ui.renderError(els.resultsNote, `Search: ${err.message}`);
  }
}

function pickSeed(result) {
  document.body.classList.add("has-seed");
  state.seedId = result.id;
  els.searchInput.value = `${result.title} — ${result.artist}`;
  els.searchResults.hidden = true;
  els.searchResults.textContent = "";
  els.findMatchesBtn.hidden = false;
  els.seedCard.hidden = true;
  state.pool = [];
  state.chips = [];
  rerenderFilterBar();
  els.results.textContent = "";
  els.resultsNote.hidden = true;
}

els.findMatchesBtn.addEventListener("click", async () => {
  if (!state.seedId) return;
  els.findMatchesBtn.disabled = true;
  ui.renderProgress(els.matchProgress, "Starting...");
  els.results.textContent = "";
  els.resultsNote.hidden = true;

  try {
    const jobId = await api.startMatch(state.seedId);
    const result = await api.pollUntilDone(jobId, api.pollMatch, (progress) =>
      ui.renderProgress(els.matchProgress, progress)
    );
    state.seed = result.seed;
    state.pool = result.results;
    state.chips = [];
    ui.renderSeedCard(els.seedCard, state.seed);
    rerenderFilterBar();
    rerenderResults();
  } catch (err) {
    ui.renderError(els.resultsNote, err.message);
  } finally {
    ui.renderProgress(els.matchProgress, "");
    els.findMatchesBtn.disabled = false;
  }
});

els.sortSelect.addEventListener("change", () => {
  state.sortBy = els.sortSelect.value;
  rerenderResults();
});

els.clearFiltersBtn.addEventListener("click", () => {
  state.chips = [];
  rerenderFilterBar();
  rerenderResults();
});

els.filterInput.addEventListener("input", updateSuggestions);

els.filterInput.addEventListener("focus", () => {
  if (els.filterInput.value.trim()) updateSuggestions();
});

els.filterInput.addEventListener("blur", () => {
  // Delay so a suggestion's mousedown (which preventDefault()s the blur
  // already) still has time to fire its click before we clear the list.
  setTimeout(closeSuggestions, 100);
});

els.filterInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (state.suggestions.length === 0) return;
    state.activeSuggestionIndex = (state.activeSuggestionIndex + 1) % state.suggestions.length;
    ui.renderSuggestions(els.filterSuggestions, state.suggestions, state.activeSuggestionIndex, onPickSuggestion);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (state.suggestions.length === 0) return;
    state.activeSuggestionIndex =
      (state.activeSuggestionIndex - 1 + state.suggestions.length) % state.suggestions.length;
    ui.renderSuggestions(els.filterSuggestions, state.suggestions, state.activeSuggestionIndex, onPickSuggestion);
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (state.activeSuggestionIndex >= 0 && state.suggestions[state.activeSuggestionIndex]) {
      onPickSuggestion(state.suggestions[state.activeSuggestionIndex]);
    }
  } else if (e.key === "Escape") {
    closeSuggestions();
  } else if (e.key === "Backspace" && els.filterInput.value === "" && state.chips.length > 0) {
    state.chips.pop();
    rerenderFilterBar();
    rerenderResults();
  }
});

// `/` focuses the filter box from anywhere on the page (unless the user
// is already typing in a text field).
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
    e.preventDefault();
    els.filterInput.focus();
  }
});

els.quitBtn.addEventListener("click", async () => {
  if (!confirm("Stop the Cue server?")) return;
  ui.setStatus(els.status, "Stopping...");
  await api.shutdown();
  ui.setStatus(els.status, "Stopped. You can close this tab.");
  document.body.classList.add("stopped");
});

// Space toggles play/pause on a focused preview button, without also
// scrolling the page (the default Space behavior on a focused button).
document.addEventListener("keydown", (e) => {
  if (e.key === " " && document.activeElement?.classList.contains("btn-ghost")) {
    e.preventDefault();
    document.activeElement.click();
  }
});

ui.setStatus(els.status, "Ready");

// Detect the server going away while the page is open (closed terminal,
// crash, `cue.py stop`) and show a clear message instead of a blank or
// stuck-looking page. A couple of consecutive misses avoids flapping on
// one slow/dropped request.
const HEALTH_POLL_MS = 8000;
let consecutiveHealthFailures = 0;

async function pollServerHealth() {
  const healthy = await api.isHealthy();
  if (healthy) {
    consecutiveHealthFailures = 0;
    els.offlineOverlay.hidden = true;
  } else {
    consecutiveHealthFailures += 1;
    if (consecutiveHealthFailures >= 2) {
      els.offlineOverlay.hidden = false;
    }
  }
}

setInterval(pollServerHealth, HEALTH_POLL_MS);

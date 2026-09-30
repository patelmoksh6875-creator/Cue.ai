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
  artistFilters: document.getElementById("artist-filters"),
  genreFilters: document.getElementById("genre-filters"),
  sortSelect: document.getElementById("sort-select"),
  clearFiltersBtn: document.getElementById("clear-filters-btn"),
  resultsNote: document.getElementById("results-note"),
  results: document.getElementById("results"),
  player: document.getElementById("player"),
};

const state = {
  seed: null,
  seedId: null,
  pool: [], // full RESULT_POOL from the server
  selectedArtists: new Set(),
  selectedGenres: new Set(),
  sortBy: "match_pct",
  activePlayButton: null,
};

function rerenderResults() {
  const { shown, totalMatchingFilter } = filters.visibleResults(
    state.pool,
    { artists: state.selectedArtists, genres: state.selectedGenres },
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
  ui.renderFilterChips(
    els.artistFilters,
    filters.availableArtists(state.pool),
    state.selectedArtists,
    (value) => {
      toggleSetMember(state.selectedArtists, value);
      rerenderFilterBar();
      rerenderResults();
    }
  );
  ui.renderFilterChips(
    els.genreFilters,
    filters.availableGenres(state.pool),
    state.selectedGenres,
    (value) => {
      toggleSetMember(state.selectedGenres, value);
      rerenderFilterBar();
      rerenderResults();
    }
  );
}

function toggleSetMember(set, value) {
  if (set.has(value)) set.delete(value);
  else set.add(value);
}

function playPreview(trackId, button) {
  if (state.activePlayButton && state.activePlayButton !== button) {
    state.activePlayButton.textContent = "▶ Preview";
  }
  if (els.player.dataset.trackId === String(trackId) && !els.player.paused) {
    els.player.pause();
    button.textContent = "▶ Preview";
    state.activePlayButton = null;
    return;
  }
  els.player.src = api.previewUrl(trackId);
  els.player.dataset.trackId = String(trackId);
  els.player.hidden = false;
  els.player.play();
  button.textContent = "⏸ Pause";
  state.activePlayButton = button;
}

els.player.addEventListener("ended", () => {
  if (state.activePlayButton) state.activePlayButton.textContent = "▶ Preview";
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
  state.seedId = result.id;
  els.searchInput.value = `${result.title} — ${result.artist}`;
  els.searchResults.hidden = true;
  els.searchResults.textContent = "";
  els.findMatchesBtn.hidden = false;
  els.seedCard.hidden = true;
  state.pool = [];
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
    state.selectedArtists.clear();
    state.selectedGenres.clear();
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
  state.selectedArtists.clear();
  state.selectedGenres.clear();
  rerenderFilterBar();
  rerenderResults();
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

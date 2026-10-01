// Pure functions: client-side filtering/sorting of the scored result pool.
// No DOM, no network -- fully testable and instant, since the pool is
// already fetched and scored server-side (see RESULT_POOL in config.py).

export function availableArtists(pool) {
  return [...new Set(pool.map((r) => r.artist))].sort();
}

export function availableGenres(pool) {
  return [...new Set(pool.map((r) => r.genre.name))].sort();
}

// Filters are AND across fields (artist AND genre), OR within a field.
export function applyFilters(pool, { artists, genres } = {}) {
  return pool.filter((r) => {
    const artistOk = !artists || artists.size === 0 || artists.has(r.artist);
    const genreOk = !genres || genres.size === 0 || genres.has(r.genre.name);
    return artistOk && genreOk;
  });
}

export function applySort(results, sortBy) {
  const sorted = [...results];
  if (sortBy === "bpm") {
    sorted.sort((a, b) => (b.bpm || 0) - (a.bpm || 0));
  } else if (sortBy === "key") {
    sorted.sort((a, b) => (b.breakdown_pct.key || 0) - (a.breakdown_pct.key || 0));
  } else {
    sorted.sort((a, b) => b.match_pct - a.match_pct);
  }
  return sorted;
}

// The full pipeline: filter the pool, sort, then take the top
// resultCount for display -- refilling from the pool instead of
// leaving a handful of results after filtering.
export function visibleResults(pool, filters, sortBy, resultCount) {
  const filtered = applyFilters(pool, filters);
  const sorted = applySort(filtered, sortBy);
  return { shown: sorted.slice(0, resultCount), totalMatchingFilter: filtered.length };
}

// Case-insensitive, accent-insensitive normalization for forgiving
// (prefix and substring) suggestion matching.
export function normalizeForMatch(text) {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

const MAX_SUGGESTIONS = 8;

// Builds the autocomplete dropdown: matching artists and genres from the
// scored pool (instant, no network), excluding anything already picked
// as a chip. Each suggestion is {type: "artist"|"genre", value}.
export function buildSuggestions(pool, queryText, selected = { artists: new Set(), genres: new Set() }) {
  const needle = normalizeForMatch(queryText);
  if (!needle) return [];

  const artists = availableArtists(pool).filter(
    (a) => !selected.artists?.has(a) && normalizeForMatch(a).includes(needle)
  );
  const genres = availableGenres(pool).filter(
    (g) => !selected.genres?.has(g) && normalizeForMatch(g).includes(needle)
  );

  // Prefix matches first, then substring matches, within each type.
  const byPrefixFirst = (values) => {
    const starts = values.filter((v) => normalizeForMatch(v).startsWith(needle));
    const rest = values.filter((v) => !normalizeForMatch(v).startsWith(needle));
    return [...starts, ...rest];
  };

  const suggestions = [
    ...byPrefixFirst(artists).map((value) => ({ type: "artist", value })),
    ...byPrefixFirst(genres).map((value) => ({ type: "genre", value })),
  ];
  return suggestions.slice(0, MAX_SUGGESTIONS);
}

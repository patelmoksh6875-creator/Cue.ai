// Rendering only. Every untrusted string (song titles, artist names, tags
// -- all from external APIs) goes through textContent/setAttribute, never
// innerHTML, so nothing from Deezer/Last.fm can inject markup.

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function matchBand(pct) {
  if (pct >= 80) return "strong";
  if (pct >= 60) return "good";
  return "fair";
}

export function renderSearchResults(container, results, onPick) {
  container.textContent = "";
  if (results.length === 0) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  for (const r of results) {
    const li = el("li", "search-result-item");
    const btn = el("button", "search-result-btn");
    btn.type = "button";
    btn.append(el("span", "sr-title", r.title), el("span", "sr-artist", ` — ${r.artist}`));
    btn.addEventListener("click", () => onPick(r));
    li.appendChild(btn);
    container.appendChild(li);
  }
}

export function renderSeedCard(container, seed) {
  container.textContent = "";
  container.hidden = false;
  container.appendChild(el("div", "seed-title", seed.title));
  container.appendChild(el("div", "seed-artist", seed.artist));
  const meta = el("div", "seed-meta");
  meta.appendChild(el("span", "pill", seed.bpm ? `${seed.bpm} BPM` : "BPM unknown"));
  if (seed.camelot) meta.appendChild(el("span", "pill", seed.camelot));
  meta.appendChild(el("span", "pill pill-genre", seed.genre.name));
  container.appendChild(meta);
}

export function renderProgress(container, text) {
  if (!text) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  container.textContent = text;
}

export function renderError(container, message) {
  container.hidden = false;
  container.textContent = "";
  container.className = "results-note error";
  container.appendChild(el("span", null, `Error: ${message}`));
}

export function renderResultsNote(container, shownCount, totalMatchingFilter, resultCount) {
  container.className = "results-note";
  if (totalMatchingFilter === 0) {
    container.hidden = false;
    container.textContent = "No results match the current filters.";
    return;
  }
  if (totalMatchingFilter < resultCount) {
    container.hidden = false;
    container.textContent = `Only ${totalMatchingFilter} match${totalMatchingFilter === 1 ? "" : "es"} in this pool for the current filters.`;
    return;
  }
  container.hidden = true;
}

export function renderMixNote(container, note, warnings) {
  container.hidden = false;
  container.className = "results-note";
  container.textContent = "";
  if (note) container.appendChild(el("div", null, note));
  if (warnings?.key_incompatible) {
    container.appendChild(el("div", "mix-warning", "⚠ Keys are not close on the Camelot wheel -- expect clashing."));
  }
  if (warnings?.stretch_exceeds_quality) {
    container.appendChild(
      el("div", "mix-warning", `⚠ Tempo stretch was ${Math.round(warnings.stretch_pct * 100)}% -- quality may be degraded.`)
    );
  }
  if (warnings?.low_confidence_bpm) {
    container.appendChild(el("div", "mix-warning", "⚠ Low-confidence BPM on one track -- the snippet may sound off-grid even for a good pair."));
  }
}

// Dropdown suggestions while typing in the filter box. `suggestions` is
// [{type: "artist"|"genre", value}], plus an optional synthetic
// "Search Deezer for <term>" row appended by the caller when nothing in
// the pool matches. `activeIndex` highlights one row for arrow-key nav.
export function renderSuggestions(container, suggestions, activeIndex, onPick) {
  container.textContent = "";
  if (suggestions.length === 0) {
    container.hidden = true;
    container.closest(".filter-search-row")?.querySelector("input")
      ?.setAttribute("aria-expanded", "false");
    return;
  }
  container.hidden = false;
  container.closest(".filter-search-row")?.querySelector("input")
    ?.setAttribute("aria-expanded", "true");

  suggestions.forEach((s, i) => {
    const li = el("li", "filter-suggestion");
    li.id = `filter-suggestion-${i}`;
    li.setAttribute("role", "option");
    if (i === activeIndex) li.classList.add("active");
    if (s.wider) {
      li.classList.add("filter-suggestion-wider");
      li.appendChild(el("span", null, `Search Deezer for "${s.value}" that match this seed`));
    } else {
      li.appendChild(el("span", "filter-suggestion-tag", s.type === "artist" ? "Artist" : "Genre"));
      li.appendChild(el("span", null, s.value));
    }
    li.addEventListener("mousedown", (e) => {
      e.preventDefault(); // keep focus in the input, don't blur before the click registers
      onPick(s);
    });
    container.appendChild(li);
  });
}

export function renderChips(container, chips, onRemove) {
  container.textContent = "";
  for (const chip of chips) {
    const pill = el("span", "filter-chip");
    pill.appendChild(el("span", null, `${chip.type === "artist" ? "Artist" : "Genre"}: ${chip.value}`));
    const removeBtn = el("button", null, "✕");
    removeBtn.type = "button";
    removeBtn.setAttribute("aria-label", `Remove filter ${chip.value}`);
    removeBtn.addEventListener("click", () => onRemove(chip));
    pill.appendChild(removeBtn);
    container.appendChild(pill);
  }
}

function bpmLine(result) {
  if (!result.bpm) return "BPM unknown";
  let line = `${result.bpm} BPM`;
  if (result.bpm_relation === "half-time") line += " (half-time)";
  else if (result.bpm_relation === "double-time") line += " (double-time)";
  return line;
}

export function renderResults(container, results, { onPlayPreview, onPreviewMix }) {
  container.textContent = "";
  for (const [index, r] of results.entries()) {
    const card = el("div", "result-card");

    const rank = el("div", "result-rank", String(index + 1));
    card.appendChild(rank);

    const main = el("div", "result-main");
    main.appendChild(el("div", "result-title", r.title));
    main.appendChild(el("div", "result-artist", r.artist));

    const meta = el("div", "result-meta");
    const bpmPill = el("span", "pill", bpmLine(r));
    if (r.bpm_confidence !== null && r.bpm_confidence < 0.4) {
      bpmPill.classList.add("pill-low-confidence");
      bpmPill.title = "Low-confidence BPM estimate (short/ambiguous preview)";
    }
    meta.appendChild(bpmPill);
    if (r.camelot) meta.appendChild(el("span", "pill", r.camelot));
    meta.appendChild(el("span", "pill pill-genre", r.genre.name + (r.genre.source === "tag" ? " (tag)" : "")));
    meta.appendChild(el("span", `pill pill-label pill-${r.label}`, r.label));
    main.appendChild(meta);
    card.appendChild(main);

    const matchBox = el("div", `match-box match-${matchBand(r.match_pct)}`);
    matchBox.appendChild(el("div", "match-pct", `${r.match_pct}%`));
    matchBox.appendChild(el("div", "match-label", "match"));
    matchBox.title = "Relative match score from weighted factors, not a probability the mix will sound good.";
    card.appendChild(matchBox);

    const actions = el("div", "result-actions");
    const playBtn = el("button", "btn btn-ghost", "▶ Preview");
    playBtn.type = "button";
    playBtn.addEventListener("click", () => onPlayPreview(r.id, playBtn));
    actions.appendChild(playBtn);

    const mixBtn = el("button", "btn btn-ghost", "Preview mix");
    mixBtn.type = "button";
    mixBtn.addEventListener("click", () => onPreviewMix(r, mixBtn));
    actions.appendChild(mixBtn);

    card.appendChild(actions);
    container.appendChild(card);
  }
}

export function setStatus(container, text) {
  container.textContent = text;
}

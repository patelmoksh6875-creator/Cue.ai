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

const SOURCE_CHOICES = [
  ["auto", "Auto"],
  ["instrumental", "Instrumental"],
  ["beat_view", "Beat view"],
  ["full_mix", "Full mix"],
];

function sourceLine(song) {
  const line = el("div", "mix-song");
  line.appendChild(el("strong", null, `${song.title}: `));
  line.appendChild(el("span", null, song.source_label));
  if (song.instrumental) {
    line.appendChild(
      el("div", "mix-sub", `Matched instrumental: ${song.instrumental.title} \u2014 ${song.instrumental.artist} (${song.instrumental.from})`)
    );
  }
  const bpm = el("div", "mix-sub",
    `Tempo on this audio: ${song.bpm_chosen} BPM (full mix: ${song.bpm_full_mix})` +
    (song.bpm_changed ? " \u2014 changed" : "") +
    (song.beat_grid_changed ? "; beat grid differs from the full mix" : ""));
  line.appendChild(bpm);
  return line;
}

// Mix panel: sources used, toggle, window choices, analysis, warnings and
// the honest limitation note. Text only via textContent (API strings).
export function renderMixPanel(container, result, selected, handlers) {
  container.textContent = "";
  container.hidden = false;
  container.appendChild(el("div", "mix-title", "Mix preview"));
  container.appendChild(sourceLine(result.a));
  container.appendChild(sourceLine(result.b));

  const row = el("div", "mix-row");
  row.appendChild(el("span", "mix-label", "Audio"));
  for (const [value, label] of SOURCE_CHOICES) {
    const b = el("button", "btn btn-ghost" + (value === selected.source ? " is-on" : ""), label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(value === selected.source));
    b.addEventListener("click", () => handlers.onSource(value));
    row.appendChild(b);
  }
  container.appendChild(row);

  const wrow = el("div", "mix-row");
  wrow.appendChild(el("span", "mix-label", "Window"));
  for (const w of result.windows) {
    const b = el("button", "btn btn-ghost" + (w.rank === result.window_rank ? " is-on" : ""),
      `${w.rank + 1} (${Math.round(w.score * 100)}%)`);
    b.type = "button";
    b.title = `A from ${w.a_start}s, B from ${w.b_start}s; kick-pattern match ${Math.round(w.drum_corr * 100)}%`;
    b.addEventListener("click", () => handlers.onWindow(w.rank));
    wrow.appendChild(b);
  }
  container.appendChild(wrow);

  container.appendChild(el("div", "mix-sub",
    `Transition: ${result.blend_beats} beats. Kick alignment: ${Math.round(result.alignment.kick_corr * 100)}%` +
    (result.alignment.well_aligned ? "" : " (weak)")));

  for (const m of result.warnings.messages) container.appendChild(el("div", "mix-warning", `Note: ${m}`));
  container.appendChild(el("div", "mix-note", result.note));
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

    const matchBox = el("div", "match-box");
    matchBox.style.setProperty("--pct", String(r.match_pct));
    const inner = el("div", "match-inner");
    inner.appendChild(el("div", "match-pct", `${r.match_pct}%`));
    inner.appendChild(el("div", "match-label", "match"));
    matchBox.appendChild(inner);
    matchBox.setAttribute("role", "img");
    matchBox.setAttribute("aria-label", `${r.match_pct} percent match`);
    matchBox.title = "Relative match score from weighted factors, not a probability the mix will sound good.";
    card.appendChild(matchBox);

    const actions = el("div", "result-actions");
    const playBtn = el("button", "btn btn-ghost", "Play");
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

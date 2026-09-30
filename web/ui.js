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

export function renderFilterChips(container, values, selectedSet, onToggle) {
  container.textContent = "";
  for (const value of values) {
    const chip = el("button", "chip", value);
    chip.type = "button";
    if (selectedSet.has(value)) chip.classList.add("chip-selected");
    chip.addEventListener("click", () => onToggle(value));
    container.appendChild(chip);
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

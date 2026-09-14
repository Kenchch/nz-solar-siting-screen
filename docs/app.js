const fmt = new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 0 });
let dataset;

function renderCandidates(sortKey = "screen_score") {
  const rows = [...dataset.top_sites].sort((a, b) => b[sortKey] - a[sortKey]);
  const eastings = rows.map(site => site.centroid_easting);
  const northings = rows.map(site => site.centroid_northing);
  const minE = Math.min(...eastings), maxE = Math.max(...eastings);
  const minN = Math.min(...northings), maxN = Math.max(...northings);
  document.querySelector("#candidate-rows").innerHTML = rows.map(site => `
    <tr>
      <td><strong>${site.site_id}</strong><br><small>${fmt.format(site.area_ha)} ha</small></td>
      <td>${Number(site.screen_score).toFixed(2)}</td>
      <td>${fmt.format(site.grid_line_m)} / ${fmt.format(site.road_proxy_m)} m<br><small>shift ${site.rank_shift}</small></td>
      <td class="${site.S05_hpl_flag ? "flag" : "clear"}">${site.S05_hpl_flag ? "LUC review" : "clear flag"}</td>
    </tr>`).join("");
  document.querySelector("#map-points").innerHTML = rows.map(site => {
    const x = 14 + 72 * (site.centroid_easting - minE) / Math.max(1, maxE - minE);
    const y = 14 + 72 * (maxN - site.centroid_northing) / Math.max(1, maxN - minN);
    return `<span class="map-point" style="left:${x}%;top:${y}%" data-label="${site.site_id}"></span>`;
  }).join("");
}

function renderChart(rates) {
  const width = 760, height = 330, left = 58, right = 24, top = 30, bottom = 44;
  const hasLoad = rates.every(d => typeof d.load_capture_rate === "number");
  const values = rates.flatMap(d => [d.solar_capture_rate * 100, d.flat_capture_rate * 100]
    .concat(hasLoad ? [d.load_capture_rate * 100] : []));
  const min = Math.floor((Math.min(...values) - 4) / 5) * 5;
  const max = Math.ceil((Math.max(...values) + 4) / 5) * 5;
  const x = i => left + i * (width - left - right) / Math.max(1, rates.length - 1);
  const y = v => top + (max - v) * (height - top - bottom) / (max - min);
  const solarPoints = rates.map((d, i) => `${x(i)},${y(d.solar_capture_rate * 100)}`).join(" ");
  const flatPoints = rates.map((d, i) => `${x(i)},${y(d.flat_capture_rate * 100)}`).join(" ");
  const loadPoints = hasLoad ? rates.map((d, i) => `${x(i)},${y(d.load_capture_rate * 100)}`).join(" ") : "";
  const ticks = [min, (min + max) / 2, max];
  document.querySelector("#capture-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    ${ticks.map(t => `<line x1="${left}" y1="${y(t)}" x2="${width-right}" y2="${y(t)}" stroke="#254147"/><text class="chart-label" x="${left-10}" y="${y(t)+4}" text-anchor="end">${t.toFixed(0)}%</text>`).join("")}
    <polyline points="${flatPoints}" fill="none" stroke="#a8dbe5" stroke-width="2" stroke-dasharray="7 6"/>
    ${hasLoad ? `<polyline points="${loadPoints}" fill="none" stroke="#f19ad6" stroke-width="2.5"/>` : ""}
    <polyline points="${solarPoints}" fill="none" stroke="#f7c948" stroke-width="4"/>
    ${rates.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.solar_capture_rate*100)}" r="5" fill="#071113" stroke="#f7c948" stroke-width="3"/><text class="chart-label" x="${x(i)}" y="${height-16}" text-anchor="middle">${d.year}</text><text class="chart-value" x="${x(i)}" y="${y(d.solar_capture_rate*100)-12}" text-anchor="middle">${(d.solar_capture_rate*100).toFixed(0)}%</text>`).join("")}
    <text class="chart-label" x="${left}" y="14">CAPTURE RATE · OUTPUT-WEIGHTED PRICE / MEAN PRICE</text>
    <text class="chart-label" x="${width - right}" y="14" text-anchor="end">SOLAR SHAPE${hasLoad ? " · ISL0661 METERED LOAD" : ""} · FLAT CONTROL</text>
  </svg>`;
}

function renderDecomposition(rates) {
  const host = document.querySelector("#decomposition-chart");
  if (!host || !rates.every(d => typeof d.seasonal_capture_rate === "number")) return;
  const width = 760, height = 330, left = 58, right = 24, top = 30, bottom = 44;
  const seasonal = rates.map(d => (d.seasonal_capture_rate - 1) * 100);
  const intraday = rates.map(d => d.intraday_capture_points * 100);
  const limit = Math.ceil(Math.max(4, ...seasonal.concat(intraday).map(Math.abs)) / 5) * 5;
  const band = (width - left - right) / rates.length;
  const y = v => top + (limit - v) * (height - top - bottom) / (2 * limit);
  const bar = (index, value, offset, fill) => {
    const barWidth = band * 0.3;
    const x = left + index * band + band / 2 + offset * barWidth * 0.55 - barWidth / 2;
    const zero = y(0), end = y(value);
    return `<rect x="${x}" y="${Math.min(zero, end)}" width="${barWidth}" height="${Math.abs(end - zero)}" fill="${fill}"/>`;
  };
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    ${[-limit, 0, limit].map(tick => `<line x1="${left}" y1="${y(tick)}" x2="${width - right}" y2="${y(tick)}" stroke="#254147"/><text class="chart-label" x="${left - 10}" y="${y(tick) + 4}" text-anchor="end">${tick > 0 ? "+" : ""}${tick}</text>`).join("")}
    ${rates.map((d, i) => bar(i, seasonal[i], -1, "#5bd6b0") + bar(i, intraday[i], 1, "#f7c948")
      + `<text class="chart-label" x="${left + i * band + band / 2}" y="${height - 16}" text-anchor="middle">${d.year}</text>`).join("")}
    <text class="chart-label" x="${left}" y="14">PERCENTAGE POINTS · SEASONAL (GREEN) VS INTRADAY (YELLOW)</text>
  </svg>`;
}

function renderOsmStudy(study) {
  const host = document.querySelector("#osm-rows");
  const scope = document.querySelector("#osm-scope");
  if (!host) return;
  if (!study) {
    host.innerHTML = `<tr><td colspan="4">Run scripts/osm_grid_study.py to populate this table.</td></tr>`;
    return;
  }
  if (scope) {
    scope.textContent = `${study.sites_passing_area_and_width.toLocaleString("en-NZ")} OSM farmland polygons passing area and width`;
  }
  const metres = value => (value >= 1000
    ? `${(value / 1000).toFixed(1)} km`
    : `${Math.round(value)} m`);
  const names = {
    transmission_110kv_plus: "≥110 kV transmission",
    subtransmission_33_66kv: "33–66 kV connection tier",
    distribution_22kv: "≤22 kV distribution",
  };
  const tiers = Object.keys(names).filter(tier => study.median_distance_m[`${tier}_m`] !== undefined);
  const rows = tiers.map(tier => {
    const correlation = study.rank_correlation[`${tier}_m|road_m`].spearman_rho;
    const highlight = tier === study.connection_tier;
    return `
    <tr>
      <td>${highlight ? "<strong>" : ""}${names[tier]}${highlight ? "</strong>" : ""}
        ${highlight ? "<br><small>what a project actually connects to</small>" : ""}</td>
      <td>${study.voltage_tier_features[tier].toLocaleString("en-NZ")}</td>
      <td>${metres(study.median_distance_m[`${tier}_m`])}</td>
      <td>${correlation.toFixed(2)}<br><small>r&sup2; ${(study.rank_correlation[`${tier}_m|road_m`].variance_explained * 100).toFixed(1)}%</small></td>
    </tr>`;
  });
  rows.push(`
    <tr>
      <td>Road centrelines</td>
      <td>${study.road_features.toLocaleString("en-NZ")}</td>
      <td>${metres(study.median_distance_m.road_m)}</td>
      <td>—</td>
    </tr>`);
  host.innerHTML = rows.join("");
}

function renderAerial(study) {
  const panel = document.querySelector("#aerial-panel");
  const text = document.querySelector("#aerial-summary");
  const review = study && study.aerial_review;
  if (!panel || !review || !review.by_sample) return;
  const cards = review.by_sample;
  const order = Object.keys(cards).sort();
  const terrain = study.terrain_water;

  if (text) {
    const a = cards.A, b = cards.B;
    text.textContent = `Sample A is the ${a.reviewed} largest disagreements: ${a.not_developable} are not developable land. Sample B is the next ${b.reviewed}, labelled only after the rules were frozen: ${b.not_developable} are. B is the milder sample by construction, and it is the one that tests whether the rules generalise.`;
  }
  const reviewedHost = document.querySelector("#aerial-reviewed");
  if (reviewedHost) {
    reviewedHost.textContent = review.reviewed;
  }
  const rulesHost = document.querySelector("#aerial-rules");
  if (rulesHost) {
    const b = cards.B;
    rulesHost.textContent = `On the held-out sample the rules exclude ${b.excluded_total} of those ${b.not_developable}, flag ${b.flagged_only_by_coast} more for coastal review, miss ${b.neither_excluded_nor_flagged.length} — both land-use failures no terrain rule can see — and wrongly exclude ${b.developable_sites_wrongly_excluded} good site over a farm irrigation pond.`;
  }
  const populationHost = document.querySelector("#aerial-population");
  if (populationHost && terrain) {
    const share = terrain.excluded_by_either / study.sites_passing_area_and_width;
    populationHost.textContent = `${terrain.excluded_by_either} of ${study.sites_passing_area_and_width.toLocaleString("en-NZ")} (${(share * 100).toFixed(1)}%)`;
  }

  const width = 760, height = 330, left = 46, right = 24;
  const bandTop = 58, bandHeight = 46, gap = 96;
  const span = width - left - right;
  const rows = order.map((name, index) => {
    const card = cards[name];
    const y = bandTop + index * gap;
    const bad = card.not_developable, total = card.reviewed;
    const badWidth = span * (bad / total);
    const excludedWidth = span * (card.excluded_total / total);
    const flaggedWidth = span * ((card.excluded_total + card.flagged_only_by_coast) / total);
    const label = name === "A" ? "A · IN-SAMPLE" : "B · HELD OUT";
    return `
    <text class="chart-label" x="${left}" y="${y - 10}">${label} — ${bad} OF ${total} NOT DEVELOPABLE (${(card.false_positive_rate * 100).toFixed(0)}%)</text>
    <rect x="${left}" y="${y}" width="${span}" height="${bandHeight}" fill="#12343b"/>
    <rect x="${left}" y="${y}" width="${badWidth}" height="${bandHeight}" fill="#f7c948"/>
    <rect x="${left}" y="${y + bandHeight - 14}" width="${flaggedWidth}" height="14" fill="#2d6a9f"/>
    <rect x="${left}" y="${y + bandHeight - 14}" width="${excludedWidth}" height="14" fill="#5bd6b0"/>
    <text x="${left + 12}" y="${y + 24}" fill="#071113" font-size="17" font-weight="700">${card.excluded_total} excluded · ${card.flagged_only_by_coast} flagged · ${card.neither_excluded_nor_flagged.length} missed</text>`;
  }).join("");

  panel.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <text class="chart-label" x="${left}" y="26">TWO LABELLED SAMPLES, NEVER POOLED</text>
    ${rows}
    <text class="chart-label" x="${left}" y="${bandTop + order.length * gap + 6}">GREEN EXCLUDED BY S-08 SLOPE OR S-09 WATER · BLUE FLAGGED ONLY BY S-10 COAST</text>
    <text class="chart-label" x="${left}" y="${bandTop + order.length * gap + 30}">SELECTED ON DISAGREEMENT — NEITHER RATE DESCRIBES THE CANDIDATE POPULATION</text>
  </svg>`;
}

function renderTilt(rows) {
  const host = document.querySelector("#tilt-rows");
  if (!host) return;
  if (!Array.isArray(rows) || rows.length === 0) {
    host.innerHTML = `<tr><td colspan="4">Tilt sensitivity unavailable.</td></tr>`;
    return;
  }
  host.innerHTML = rows.map(row => `
    <tr>
      <td><strong>${Number(row.tilt_deg).toFixed(0)}°</strong><br><small>${Number(row.tilt_deg) === 0 ? "horizontal proxy" : "north-facing fixed"}</small></td>
      <td>${Number(row.december_over_june_output).toFixed(2)}×</td>
      <td>${(row.mean_capture_rate * 100).toFixed(1)}%</td>
      <td>${(row.minimum_capture_rate * 100).toFixed(1)}%</td>
    </tr>`).join("");
}

fetch("data.json")
  .then(response => { if (!response.ok) throw new Error("Results unavailable"); return response.json(); })
  .then(data => {
    dataset = data;
    document.querySelector("#candidate-count").textContent = data.candidates;
    document.querySelector("#total-count").textContent = data.total;
    // A null jaccard means neither shortlist could be drawn, which Number()
    // turns into 0 and toFixed renders as "0.00" - a measurement of perfect
    // disagreement, published from no measurement at all.
    const jaccard = data.grid_comparison.jaccard;
    document.querySelector("#grid-overlap").textContent =
      typeof jaccard === "number" && Number.isFinite(jaccard) ? jaccard.toFixed(2) : "N/A";
    const latest = [...data.capture_rates].reverse().find(row => row.complete_year);
    document.querySelector("#latest-capture").textContent = `${(latest.solar_capture_rate * 100).toFixed(0)}%`;
    document.querySelector("#latest-year").textContent = latest.year;
    document.querySelector("#price-status").textContent = data.price_status;
    const worst = data.capture_rates.reduce((a, b) => (a.solar_capture_rate <= b.solar_capture_rate ? a : b));
    const intradayHost = document.querySelector("#intraday-term");
    if (intradayHost && typeof worst.intraday_capture_points === "number") {
      const points = worst.intraday_capture_points * 100;
      intradayHost.textContent = `${points >= 0 ? "+" : "−"}${Math.abs(points).toFixed(1)} pts`;
      intradayHost.nextElementSibling.textContent =
        `${worst.year}; the other ${((1 - worst.seasonal_capture_rate) * 100).toFixed(0)} points are seasonal`;
    }
    renderCandidates();
    renderChart(data.capture_rates);
    renderDecomposition(data.capture_rates);
    renderTilt(data.tilt_sensitivity);
    renderOsmStudy(data.osm_grid_study);
    renderAerial(data.osm_grid_study);
    const overlapNote = document.querySelector("#grid-overlap-note");
    if (overlapNote && data.osm_grid_study) {
      overlapNote.textContent = `demo n=${data.grid_comparison.n}; see the real-geometry run below`;
    }
  })
  .catch(error => {
    document.querySelector("#candidate-rows").innerHTML = `<tr><td colspan="4">${error.message}. Run the reproduction script.</td></tr>`;
  });

document.querySelector("#sort-select").addEventListener("change", event => renderCandidates(event.target.value));


const fmt = new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 0 });
let dataset;

function renderCandidates(sortKey = "screen_score") {
  const rows = [...dataset.top_sites].sort((a, b) => b[sortKey] - a[sortKey]);
  document.querySelector("#candidate-rows").innerHTML = rows.map(site => `
    <tr>
      <td><strong>${site.site_id}</strong><br><small>${fmt.format(site.area_ha)} ha</small></td>
      <td>${Number(site.screen_score).toFixed(2)}</td>
      <td>${fmt.format(site.grid_line_m)} / ${fmt.format(site.road_proxy_m)} m<br><small>shift ${site.rank_shift}</small></td>
      <td class="${site.S05_hpl_flag ? "flag" : "clear"}">${site.S05_hpl_flag ? "LUC review" : "clear flag"}</td>
    </tr>`).join("");
  document.querySelector("#map-points").innerHTML = rows.map((site, index) => {
    const x = 17 + ((site.road_proxy_m / 2600 + index * 13) % 68);
    const y = 22 + ((site.grid_line_m / 1900 + index * 17) % 60);
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
    const correlation = study.rank_correlation[`${tier}_m|road_m`];
    const highlight = tier === study.connection_tier;
    return `
    <tr>
      <td>${highlight ? "<strong>" : ""}${names[tier]}${highlight ? "</strong>" : ""}
        ${highlight ? "<br><small>what a project actually connects to</small>" : ""}</td>
      <td>${study.voltage_tier_features[tier].toLocaleString("en-NZ")}</td>
      <td>${metres(study.median_distance_m[`${tier}_m`])}</td>
      <td>${correlation.toFixed(2)}</td>
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
  if (!panel || !review) return;
  const bad = review.not_developable;
  const good = review.queued - bad;
  if (text) {
    text.textContent = `${bad} of the ${review.queued} are not developable land at all — coastal barrier spit, lagoon and wetland margin, or Banks Peninsula slope. The other ${good} are genuine flat plains blocks 7–11 km from the nearest mapped 33–66 kV line with a road along the boundary.`;
  }
  const width = 760, height = 330, top = 70, left = 40;
  const barWidth = (width - left * 2) * (bad / review.queued);
  panel.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <text class="chart-label" x="${left}" y="30">AERIAL REVIEW OF THE ${review.queued} LARGEST DISAGREEMENTS</text>
    <rect x="${left}" y="${top}" width="${width - left * 2}" height="54" fill="#12343b"/>
    <rect x="${left}" y="${top}" width="${barWidth}" height="54" fill="#f7c948"/>
    <text x="${left + 14}" y="${top + 35}" fill="#071113" font-size="22" font-weight="700">${bad} not developable</text>
    <text x="${width - left - 14}" y="${top + 35}" fill="#a8dbe5" font-size="18" text-anchor="end">${good} genuine</text>
    <text class="chart-value" x="${left}" y="${top + 100}" font-size="46">${(review.false_positive_rate * 100).toFixed(0)}%</text>
    <text class="chart-label" x="${left}" y="${top + 128}">FALSE-POSITIVE RATE OF THE ROAD PROXY'S WORST DISAGREEMENTS</text>
    <text class="chart-label" x="${left}" y="${top + 172}">COASTAL BARRIER SPIT · LAGOON AND WETLAND MARGIN · BANKS PENINSULA SLOPE</text>
    <text class="chart-label" x="${left}" y="${top + 196}">NO SLOPE RULE AND NO COASTAL-HAZARD RULE IS IMPLEMENTED IN THE BASELINE</text>
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
    document.querySelector("#grid-overlap").textContent = Number(data.grid_comparison.jaccard).toFixed(2);
    const latest = data.capture_rates[data.capture_rates.length - 1];
    document.querySelector("#latest-capture").textContent = `${(latest.solar_capture_rate * 100).toFixed(0)}%`;
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


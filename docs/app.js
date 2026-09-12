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
  const values = rates.flatMap(d => [d.solar_capture_rate * 100, d.flat_capture_rate * 100]);
  const min = Math.floor((Math.min(...values) - 4) / 5) * 5;
  const max = Math.ceil((Math.max(...values) + 4) / 5) * 5;
  const x = i => left + i * (width - left - right) / Math.max(1, rates.length - 1);
  const y = v => top + (max - v) * (height - top - bottom) / (max - min);
  const solarPoints = rates.map((d, i) => `${x(i)},${y(d.solar_capture_rate * 100)}`).join(" ");
  const flatPoints = rates.map((d, i) => `${x(i)},${y(d.flat_capture_rate * 100)}`).join(" ");
  const ticks = [min, (min + max) / 2, max];
  document.querySelector("#capture-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    ${ticks.map(t => `<line x1="${left}" y1="${y(t)}" x2="${width-right}" y2="${y(t)}" stroke="#254147"/><text class="chart-label" x="${left-10}" y="${y(t)+4}" text-anchor="end">${t.toFixed(0)}%</text>`).join("")}
    <polyline points="${flatPoints}" fill="none" stroke="#a8dbe5" stroke-width="2" stroke-dasharray="7 6"/>
    <polyline points="${solarPoints}" fill="none" stroke="#f7c948" stroke-width="4"/>
    ${rates.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.solar_capture_rate*100)}" r="5" fill="#071113" stroke="#f7c948" stroke-width="3"/><text class="chart-label" x="${x(i)}" y="${height-16}" text-anchor="middle">${d.year}</text><text class="chart-value" x="${x(i)}" y="${y(d.solar_capture_rate*100)-12}" text-anchor="middle">${(d.solar_capture_rate*100).toFixed(0)}%</text>`).join("")}
    <text class="chart-label" x="${left}" y="14">CAPTURE RATE · OUTPUT-WEIGHTED PRICE / MEAN PRICE</text>
  </svg>`;
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
    renderCandidates();
    renderChart(data.capture_rates);
  })
  .catch(error => {
    document.querySelector("#candidate-rows").innerHTML = `<tr><td colspan="4">${error.message}. Run the reproduction script.</td></tr>`;
  });

document.querySelector("#sort-select").addEventListener("change", event => renderCandidates(event.target.value));


# Canterbury Solar Siting Screen

> This is a **screening** tool, not a development decision. It ranks candidate areas from open data so that a human can look at fewer of them. The single most important variable in a real solar project — available grid hosting capacity at a specific connection point — is not public at site level and is explicitly out of scope. Nothing here should be read as a statement about any particular parcel of land.

An auditable Python workflow for utility-scale fixed-tilt PV screening in Canterbury, New Zealand. It connects three decisions that are often analysed separately: where open data suggests land may be worth reviewing, how sensitive that ranking is to incomplete network data, and what a simplified solar output shape would have captured at the ISL0661 wholesale node.

[Open the interactive findings dashboard](https://kenchch.github.io/nz-solar-siting-screen/) · [Rule register](rules/rule_register.csv) · [Policy sources](rules/SOURCES.md) · [Data acquisition](data/README.md)

![Where the capture-rate gap comes from](outputs/demo/figures/capture_rate_decomposition.png)

## Two empirical findings, two method warnings

1. **Empirical — generation is not revenue, and the reason is seasonal, not midday cannibalisation.** Official Electricity Authority half-hourly final prices at ISL0661 give apparent-solar-time capture rates from **82.5% to 110.3%** over 2019–2025 for a north-facing 25° array. Five of seven annual values are below 100%; 2019 and 2023 are above it. The worst year is 2024 at **82.5%**, a gap of 17.5 points below the time-average price. The decomposition below attributes **−17.7 points of it to seasonal mismatch**; the intraday term is **+0.2 points**, so the shape of the day actually gave a little value back. The discount is dry-year winter prices arriving when a fixed-tilt array produces least, not midday price suppression.
2. **Empirical — a road proxy tracks the low-voltage network, not the one a project can connect to.** Measured on **2,356 real Canterbury farmland polygons** that pass the area and width rules, against mapped OpenStreetMap lines split by voltage. Rank correlation with distance-to-road: **0.47** for ≤22 kV distribution, **0.11** for the 33–66 kV tier a Canterbury project actually connects at, **0.04** for ≥110 kV transmission. Roads find the poles that are everywhere and say almost nothing about the connection that matters. This is why both distances and a `verify_grid` flag stay visible and why grid distance was removed from `screen_score` entirely. See [the OSM study](#measuring-the-grid-proxy-disagreement-on-real-geometry) for the caveats, which are substantial.
3. **Method warning — the screen was missing terrain and water, and an aerial check is what found it.** Of the twenty largest grid-proxy disagreements, **11 are not developable land at all** — coastal barrier spit, wetland margin, or 14–24° peninsula slope. None is a grid problem. S-08 slope was documented as "not implemented" and there was no water or coastal rule at all; all three now exist, built from free inputs, and they **exclude 8 of those 11, flag 2 more, and miss 1**. That sample was selected on disagreement, so the 55% is the road proxy's worst cases, not a population rate.
4. **Method warning — a single width proxy changes the screening answer.** The 180 m inward-buffer test is the S-02 baseline; `2A/P` remains beside it as an audit comparator. The deterministic geometry stress case is a 200 × 200 m square: the core test passes while `2A/P` reports 100 m and fails. The run manifest reports the number of disagreements instead of hiding this modelling choice.

## Seasonal or intraday? The capture rate splits exactly

Writing each half hour's price as its daily mean plus a within-day residual makes the capture rate separate into two terms that sum to it with no remainder:

```text
capture_rate = seasonal_term + intraday_term
             = sum_d(n_d · P_d · G_d) / D   +   sum_d(n_d · cov_d) / D
```

where `P_d` and `G_d` are day `d`'s mean price and mean output, `cov_d` is the within-day price/output covariance, and `D = sum(output) × mean(price)`. The seasonal term answers *is the output in the expensive months?* The intraday term answers *is it in the expensive hours?* **Only the intraday term is price cannibalisation.** `tests/test_capture_decomposition.py` asserts the identity holds, that a purely seasonal price signal puts nothing in the intraday term, and that an artificial midday trough puts nothing in the seasonal term.

| NZ market year | Solar capture | Seasonal term | Intraday term (pts) | Metered load control |
|---:|---:|---:|---:|---:|
| 2019 | 110.3% | 100.2% | +10.1 | 102.9% |
| 2020 | 97.9% | 93.6% | +4.3 | 108.0% |
| 2021 | 91.5% | 90.7% | +0.8 | 105.5% |
| 2022 | 97.0% | 91.9% | +5.1 | 105.3% |
| 2023 | 104.5% | 105.9% | −1.4 | 102.1% |
| 2024 | 82.5% | 82.3% | +0.2 | 114.2% |
| 2025 | 92.2% | 93.9% | −1.7 | 102.2% |

The intraday term is **positive in five of seven years** and averages **+2.5 points**: the modelled solar shape currently earns a small premium *within* the day, because daytime is worth more than the overnight trough and New Zealand has almost no solar on the system yet. Reading these annual numbers as cannibalisation would be wrong.

2019 stands out at **+10.1 points**, four times the period average, and it is worth saying why. The intraday term is the output-weighted within-day price premium divided by the annual mean price, and 2019 had a large numerator over a small denominator. It is the only year in the series whose average midday block was the most expensive part of the day — 126 NZD/MWh at 10:00–16:00 against 121 in the 17:00–21:00 evening and 94 overnight — which gives a solar-weighted premium of **+11.7 NZD/MWh**, the largest in absolute terms of the seven years. It was also the second-cheapest year overall at a 116 NZD/MWh annual mean.

The contrast is 2021 and 2025, where the same calculation returns +0.8 and −1.7 points: their annual means were lifted by scarcity concentrated in the **evening** peak (210 and 169 NZD/MWh at 17:00–21:00, against 166 and 152 at midday), which a solar shape cannot reach. So 2019 is a statement about the shape of that year's day, not a sign that solar earns a premium.

What the series shows is a seasonal mismatch, and 2024 makes it visible:

![Seasonal mismatch at ISL0661 in 2024](outputs/demo/figures/seasonal_mismatch.png)

August 2024 averaged **520 NZD/MWh** during the gas and hydro squeeze while the modelled array delivered 6.6% of its annual output; December averaged **21 NZD/MWh** against 11.6% of output. The 2024 half-hourly averages have no material midday trough at all — the cheapest hours of that year were overnight, not at noon.

The December collapse is worth reading carefully, because it is the seasonal term's future in miniature. A 21 NZD/MWh monthly average is not a solar effect: it is a wet spring filling the South Island lakes into a low-demand month, so hydro spills and the market clears near zero for weeks. Summer is already the cheapest part of this market before any material PV exists. **Adding solar makes the seasonal term worse, not just the intraday one** — new summer-peaking capacity arrives in the months that are already oversupplied, deepening exactly the months where a fixed-tilt array puts most of its energy. A penetration forecast that only models midday cannibalisation will miss the larger half of the effect.

The two terms therefore call for different responses. The intraday term is a penetration question and the thing to forecast half-hourly. The seasonal term is a technology and contracting question — tilt, east–west orientation, storage duration, and how much winter-weighted hedge sits behind the asset.

### Control group: the real load shape at the same node

A flat profile is an arithmetic invariant that must return exactly 1.0, not a comparison. The Electricity Authority publishes metered grid-exit energy at ISL0661, so the local demand shape runs through the identical calculation as a genuine control. It captures **102.1%–114.2%**, above 1.0 in every year, with a positive intraday term every year (evening peak) and a seasonal term that peaks in the same dry winter that hurts solar most. That is the mirror image of the solar result and is why "generation is not revenue" is a statement about timing rather than about PV.

![Capture rate by year](outputs/demo/figures/capture_rate_by_year.png)

## Two model errors found and quantified

### 1. Tilt: the output model was labelled fixed-tilt but the geometry was horizontal

The earlier model used `sin(elevation)^1.15`, which is a horizontal-plane proxy, while every document called the asset a fixed-tilt array. It produced a December/June output ratio of **5.85×**; a north-facing 25–30° array in Canterbury is roughly 2.5–3×. Because this node prices winter so highly, an overstated seasonal swing systematically **understated** the capture rate — the error pushed directly against the headline number.

The corrected model is the cosine of the incidence angle on a north-facing plane tilted `tilt_deg` from horizontal, multiplied by a clear-sky beam transmittance (Kasten–Young air mass, Meinel transmittance) raised to the shaping exponent. Geometry carries the array orientation; transmittance carries the longer atmospheric path that weakens low winter sun. `tilt_deg: 0` recovers the horizontal plane exactly, so the old model is still runnable as a comparator.

| Array tilt | Dec / Jun output | Mean capture | Worst year | Mean seasonal | Mean intraday (pts) |
|---:|---:|---:|---:|---:|---:|
| 0° (old horizontal proxy) | 5.85× | 92.9% | 71.9% | 89.7% | +3.2 |
| **25° (baseline)** | **2.77×** | **96.6%** | **82.5%** | **94.1%** | **+2.5** |
| 35° | 2.25× | 97.7% | 86.0% | 95.5% | +2.3 |

> The horizontal-plane error was worth **7.1 percentage points** on the worst year (71.9% → 82.5%) and 3.7 points on the period mean. It moved the headline in the direction that flattered the "solar is badly discounted" story, which is exactly the direction an error is easiest not to notice.

Related, and much smaller: output is now evaluated at the **midpoint** of each trading period rather than at its opening instant, removing a systematic 15-minute lead. `midpoint_utc` is published beside `timestamp_utc` so the basis is auditable, and the join key is unchanged.

### 2. Civil clock versus solar time

The earlier model also placed solar noon at 12:00 on the civil clock, including during NZDT. The corrected model converts each UTC instant to local time, then adjusts its hour angle for longitude, UTC offset and the equation of time. The January peak moves from 12:00 to 13:30 NZDT in the half-hour model.

| NZ market year | Civil-clock model | Corrected apparent-solar model | Change (percentage points) |
|---:|---:|---:|---:|
| 2019 | 110.66% | 110.35% | −0.31 |
| 2020 | 98.50% | 97.91% | −0.59 |
| 2021 | 92.23% | 91.49% | −0.74 |
| 2022 | 97.36% | 97.00% | −0.36 |
| 2023 | 105.05% | 104.52% | −0.53 |
| 2024 | 82.28% | 82.53% | +0.25 |
| 2025 | 92.09% | 92.16% | +0.07 |

> Maximum annual shift 0.74 percentage points. Unlike the tilt error, this one was real but immaterial to the conclusion; both are reported at their actual size rather than at the size that makes a better story.

### Observation-year reconciliation

`capture_rates.csv` groups by **New Zealand market year** after converting UTC timestamps to `Pacific/Auckland`, not by the year printed at the start of the UTC timestamp. All 122,688 input rows are assigned exactly once, and the pipeline asserts that `sum(observations) == len(price input)`.

| Year label | Rows grouped by UTC year | Rows grouped by NZ market year / reported observations |
|---:|---:|---:|
| 2018 | 26 | 0 |
| 2019 | 17,520 | 17,520 |
| 2020 | 17,568 | 17,568 |
| 2021 | 17,520 | 17,520 |
| 2022 | 17,520 | 17,520 |
| 2023 | 17,520 | 17,520 |
| 2024 | 17,568 | 17,568 |
| 2025 | 17,446 | 17,472 |

The 26 UTC rows dated 2018-12-31 are the first 13 NZDT hours of market year 2019. Likewise, the NZ market-year count for 2025 includes its first 26 rows from 2024 UTC. The 2025 Electricity Authority December file is explicitly labelled `incomplete`; on the market-year basis, 2025 has 17,472 observations rather than a normal 17,520. It remains unsuitable for presentation as a final full-year statistic without rechecking the source.

## Measuring the grid-proxy disagreement on real geometry

The demo run answers "does the code work" on twelve deterministic rectangles; a Jaccard index on n = 4 is not evidence about anything. LINZ Topo50 and LCDB both need portal accounts, so `scripts/osm_grid_study.py` runs the same comparison on an open substitute with real geometry: **9,102 OpenStreetMap farmland polygons** in the Canterbury plains, of which **2,356 pass S-01 (20 ha) and S-02 (180 m width core)**, against **21,842 road centrelines** and every mapped power line in the extract.

Only the two geometric rules are applied. Land-cover class, LUC class and solar resource still need LRIS, so this is a grid-distance study, not a screening run.

### Split the network by voltage, not by OSM tag

An earlier version of this study split power lines by their OSM `power` tag, which is the wrong cut. The tag separates 131 ways tagged `line` at 66 kV from 158 ways tagged `minor_line` at the same 66 kV, while lumping 220 kV transmission and 350 kV HVDC in with the first group. A Canterbury project of tens of megawatts connects at **33 or 66 kV**. It does not connect to an HVDC pole, and a 220 kV connection is a different project with a different budget. Tiering by voltage puts each way where the engineering puts it; ways tagged with two circuits such as `66000;11000` take the higher one, HVDC is dropped outright, and the 994 untagged ways are reported rather than silently assigned.

| Voltage tier | Mapped ways | Median distance | 90th percentile | Rank correlation with road distance |
|---|---:|---:|---:|---:|
| ≥110 kV transmission | 65 | 4,864 m | 15,055 m | **0.04** |
| **33–66 kV (connection tier)** | **541** | **1,687 m** | **6,066 m** | **0.11** |
| ≤22 kV distribution | 5,134 | 13 m | 548 m | **0.47** |
| road centrelines | 21,842 | 10 m | 450 m | — |

![Grid proxy disagreement on OSM Canterbury geometry](outputs/osm/osm_grid_disagreement.png)

The ordering is the finding, and it is monotonic in voltage. A road centreline is a decent stand-in for the low-voltage network — of course it is, the poles follow the road. It is almost useless for the 33–66 kV tier a project would actually connect to: a rank correlation of 0.11 means road proximity explains about **1%** of the variance in connection-tier proximity, and the two top-50 shortlists share no sites at all. The 33–66 kV tier is also not a stand-in for transmission (correlation 0.31 between those two), so there is no single "distance to the grid" number to put in a score.

**If you take one sentence to an interview:** on real Canterbury geometry, distance to a road predicts distance to 33–66 kV at ρ = 0.11 — statistically indistinguishable from picking sites at random — while predicting distance to 11 kV at ρ = 0.47.

### The verify flag had to be re-cut too

`S06_verify_grid` originally fired when *any* proxy distance exceeded 5 km, or the rank shift reached 3. Applied to these columns that rule flags **2,348 of 2,356 sites**, and the notebook recomputes it beside the new one — a flag that fires on everything carries no information. It now tests one thing: distance to the connection tier against that tier's own review distance, which is configured per tier in `config/assumptions.yml`. At 5 km from 33–66 kV it flags **372 of 2,356 (15.8%)**, which is a queue a person can actually work through.

The absolute rank-shift trigger was dropped from the flag entirely. `rank_shift_review = 3` was chosen against eight demo fixtures; at n = 2,356 the median shift is 646, so the same constant fires on essentially every site. Rank thresholds expressed in ranks do not transfer across sample sizes. The shift stays published as a column, and it still selects the aerial review queue.

### Aerial review: 11 of the 20 worst disagreements are not developable land

All twenty of the largest connection-tier-versus-road disagreements were checked against LINZ Basemaps aerial imagery. Every verdict in [`data/aerial_review_log.csv`](data/aerial_review_log.csv) carries the date, the imagery and zoom used, **the image it was written from** (committed under [`data/aerial/`](data/aerial/)), and an `observed_detail` naming something visible in that image — an aircraft parked on a grass airstrip, a sand island in the lagoon, the distance to a surf line. A reader can open the picture and contradict the verdict; that is the point.

> **Who reviewed these.** Two passes, both by an AI agent (Claude Opus 5) working in the repository author's session, from the committed images. The log records both, and an `author_confirmed_on` column that is still empty — no person has signed the verdicts off, and the file says so rather than implying otherwise.
>
> The second pass earned its keep. It confirmed all twenty verdicts but found two errors of my own making: the first pass had recorded the mosaic as "about 1.7 km across" when 1.7 km is the *per-tile* width at this latitude and the 3 × 3 mosaic is **5.3 km**, so every distance eyeballed off an image was roughly three times too small. Those are now measured from the geometry instead of estimated by eye. It also corrected one description — a site called an "enclosed valley floor" whose polygon turns out, at 23.8° mean slope, to be mostly the steep valley sides.

**Eleven of the twenty are not developable land at all**, and none of the failures is a grid problem:

| Group | Sites | What the imagery shows |
|---|---:|---|
| Coastal barrier spit | 5 | Gravel, dune and lagoon-margin flats between a lagoon and the open coast; one is bare dune with a formed track along it. |
| Lagoon and wetland margin | 1 | Low-lying marsh at the lake edge with standing water inside the polygon. |
| Peninsula slope | 4 | Steep coastal hillsides and cliffed headlands; measured mean slope 14–24°. |
| Enclosed valley floor | 1 | Flat (3.5° mean) but boxed in by steep slopes behind a settlement, under 400 m wide. |

The last row is a correction the data made to an eyeball grouping: five of these sites looked like "peninsula slope" in the imagery, but once slope was actually measured, one of them is a flat valley floor that fails for enclosure and size rather than gradient. It is the kind of thing a rule catches and an impression does not.

The other nine are genuine flat plains blocks — centre-pivot cropping and improved pasture — sitting 7–11 km from the nearest mapped 33–66 kV line while a road runs along the boundary. Those are the real disagreements, and the ones worth a connection enquiry.

> **What the 55% is and is not.** These twenty were selected *because* they are the largest disagreements, which biases the sample towards coast and peninsula edges. **55% is the false-positive rate of the road proxy's worst cases, not of the candidate population.** The honest population statement is the one below: the new terrain and water rules exclude 206 of 2,356 sites, or 8.7%.

### Closing the gap: S-08 slope, S-09 water, S-10 coastal

The review said the screen was missing terrain and water, so the screen now has terrain and water. All three inputs are free and need no account.

| Rule | Input | Threshold | Effect on the 2,356 |
|---|---|---|---:|
| **S-08** mean slope | Copernicus GLO-30 DEM | exclude above 10° mean over the polygon | 113 excluded |
| **S-09** mapped water | OSM `natural=water`/`wetland`, `landuse=basin` | exclude on any intersection | 106 excluded |
| **S-10** coastal proximity | OSM `natural=coastline` | flag within 1,000 m | 133 flagged |

Median mean slope across the study population is 0.77° — it is the Canterbury plains — and 206 sites (8.7%) fail S-08 or S-09. `scripts/compute_site_terrain.py` downloads the DEM tiles and writes a committed per-site slope table, so the screening run itself needs no raster and no network.

GLO-30 is a **surface** model, not a terrain model: it includes shelterbelts, buildings and trees, which inflate slope locally on otherwise flat paddocks. S-08 therefore uses the mean over the polygon rather than the maximum, where a single row of poplars would dominate, and the rule is a terrain screen rather than a civil design input. A real design stage wants a bare-earth DEM.

Scored against the twenty labelled sites, keeping exclusion and flagging apart — the same distinction S-05 rests on, since a flagged site still reaches a human as a candidate:

| Outcome for the 11 non-developable sites | Count |
|---|---:|
| **Excluded** by S-08 slope | 4 |
| **Excluded** by S-09 mapped water | 4 |
| **Excluded**, total | **8** |
| Flagged only by S-10 coastal — still in the candidate set | 2 |
| Neither excluded nor flagged | 1 |

No developable site is excluded, and none is flagged either.

> **This is in-sample.** The thresholds were chosen with those twenty labels in view. The number says the rules express what the imagery showed; it is not an accuracy claim on unseen sites, and it should not be quoted as one.

The two flagged-only sites are the honest middle: both are on the barrier spit, the coastal flag fires on them, and a reviewer opening the flag would see what the imagery shows. They are not failures of the screen, but they are not exclusions either, and rounding them up to "caught" would be the kind of quiet overstatement this project exists to avoid.

The one site that trips nothing is instructive. It is a flat 312 ha barrier-spit polygon whose nearest mapped coastline is 1.3 km away, because the barrier is wide at that point. No simple setback reaches it — catching it needs a barrier-landform test or real land cover, and inventing a threshold that happens to capture this one site would be fitting the sample rather than screening. It is left uncaught and named.

### What this is not

- **OpenStreetMap is not LINZ.** Completeness varies by area and contributor; 994 mapped ways carry no voltage tag at all and sit in none of the tiers. The absence of a mapped line is not evidence that no line exists.
- **A land-use polygon is not a parcel.** Eleven of twenty says so. Real screening needs LCDB or cadastral polygons.
- **Still missing, and still blocked on credentials:** the LINZ Topo50 and LCDB versions of this same run. Nothing here should be quoted as a LINZ result.

Attribution: © OpenStreetMap contributors, ODbL 1.0. Aerial imagery © LINZ and Environment Canterbury, CC BY 4.0.

## Scope and decision logic

| Rule | Treatment | Baseline implementation |
|---|---|---|
| S-01 contiguous area | Exclude | at least 20 ha |
| S-02 usable width | Exclude | 180 m inward-buffer core; retain `2A/P` as comparator |
| S-03 land cover | Exclude | configured LCDB whitelist |
| S-04 public conservation land | Exclude | no intersection |
| S-05 highly productive land | **Flag** | LUC 1–3 → consenting review; never automatic exclusion |
| S-06 grid proximity | **Flag + published distances** | both distances, both ranks and rank shift retained; **excluded from `screen_score`** |
| S-07 solar resource | Rank | higher LENZ mean annual solar radiation ranks better |
| S-08 mean slope | Exclude | mean slope over the polygon above 10°, from Copernicus GLO-30 |
| S-09 mapped water | Exclude | any intersection with mapped standing water or wetland |
| S-10 coastal proximity | **Flag** | within 1,000 m of the open coast → hazard review |

Excluded records are written to `quarantine.gpkg` with the rule IDs that removed them. A configurable reject-rate gate aborts output when a batch looks more like a wrong input or CRS than a plausible screen.

Not covered: connection-point hosting capacity, voltage, connection cost, land ownership, parcel negotiation, geotechnical conditions, flood and wildfire risk, glare, ecology beyond the public-conservation overlay, archaeology, landscape/visual effects, mana whenua values, local plan rules, network losses, curtailment or construction access.

## Policy treatment: LUC 1–3 is not a veto

The source register was rechecked on 13 September 2026. The current instrument is the **NPS-HPL 2022 consolidated with December 2025 amendments**, effective 15 January 2026. Clause 3.9(2)(j)(i) provides a pathway for specified infrastructure where there is a functional or operational need; clause 3.9(3) requires loss of productive capacity and reverse-sensitivity effects to be minimised or mitigated. Before operative regional mapping, clause 3.5(7) also makes the transitional definition more specific than "all LUC 1–3".

This dataset only supplies LUC class, not the full planning test. S-05 is therefore a conservative screening **flag** and a prompt for a planner, not a legal conclusion. See [rules/SOURCES.md](rules/SOURCES.md) for the primary text.

## Method

### M1 — siting

All metric work is rejected unless the input CRS is EPSG:2193 (NZTM2000). Geometry rules are evaluated first; failed records are quarantined rather than deleted. Nearest network distances use `geopandas.sjoin_nearest`, backed by the spatial index, rather than a union-and-row-loop calculation. Surviving features retain both grid distances, their two ranks, absolute rank shift, HPL flag and solar rank.

`screen_score` orders a review queue from the two attributes the screen can actually measure: **solar resource and usable area**. Grid distance is deliberately not in it. An earlier version gave the two network proxies 80% of the score while the surrounding text argued that those same proxies were too unreliable to rank on — a contradiction that a weighted score is very good at hiding. Every weight and threshold now comes from [`config/assumptions.yml`](config/assumptions.yml), and `tests/test_screen_score.py` asserts that moving the powerline layer 50 km changes the published distances and leaves the ordering untouched.

### M2 — output shape

For each half hour the model computes solar declination and hour angle, the cosine of the incidence angle on a north-facing plane at the configured tilt, and a clear-sky beam transmittance from Kasten–Young relative air mass; the transmittance is raised to a documented shaping exponent and the annual mean is scaled to the configured 17.5% capacity factor. Geometry is evaluated at the midpoint of each trading period. Hour angle uses apparent solar time derived from longitude, the active NZST/NZDT UTC offset and an equation-of-time approximation.

It is a typical clear-sky timing proxy — not measured generation and not a weather model. It excludes cloud, aerosol, snow, soiling, terrain and horizon shading, degradation, tracking and inverter clipping. The published civil-clock and 0°-tilt comparators isolate the effect of each modelling choice.

All publication assumptions live in [`config/assumptions.yml`](config/assumptions.yml). Capacity-factor scaling is an invariant because the scalar cancels from capture rate. Two sensitivities are published: the shaping exponent from 1.0 to 1.3 (which moves the mean capture rate by 0.6 points) and the array tilt at 0°, 25° and 35° (which moves it by 4.8 points). Tilt is the assumption that matters.

### M3 — capture rate

For half-hour periods `t`:

```text
capture_rate = sum(price_t × output_t) / (sum(output_t) × mean(price_t))
```

The numerator is the output-weighted spot-market value. The denominator is the value the same energy would receive at the all-hours mean nodal price. Two controls run through the identical function: a flat output profile, which is an invariant that must return exactly 1.0, and the metered ISL0661 grid-exit load shape, which is a real alternative shape rather than an arithmetic identity. Every result is also published as its seasonal and intraday terms.

Trading date and trading period are converted to unique UTC instants using `Pacific/Auckland`: 46-period and 50-period daylight-saving days therefore align one-to-one. The merge is validated as one-to-one, preserves the input row count, and fails on duplicate or unmatched keys — including a load-control series that does not cover every priced period.

This is a **market-value signal, not a revenue forecast**. It uses nodal spot prices, not a PPA, and excludes loss factors, node-to-node basis, FTRs, hedges and dispatch/curtailment constraints.

## Reproduce

Python 3.11+ is required.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/reproduce.py --demo
.venv/bin/python scripts/osm_grid_study.py
.venv/bin/python -m pytest
```

On Windows use `.venv/Scripts/` in place of `.venv/bin/`. Both runs read only committed inputs, so neither needs network access. To refresh those inputs, run `scripts/download_ea_prices.py`, `scripts/download_ea_load.py`, `scripts/download_osm_networks.py` and `scripts/compute_site_terrain.py`; the last of these downloads about 90 MB of Copernicus DEM tiles, which is why its output is committed as a small per-site table and it is not part of CI. LRIS and LINZ exports require the accounts/API keys described in [data/README.md](data/README.md).

## Notebooks

- [`notebooks/01_grid_distance_comparison.ipynb`](notebooks/01_grid_distance_comparison.ipynb) — sweeps the top-N overlap on the demo fixtures, re-derives the verify-grid flag from the published distances, demonstrates that moving the powerline layer does not move `screen_score`, and then repeats the comparison on the 2,356 real OSM polygons by voltage tier, ending on the aerial verdicts.
- [`notebooks/02_capture_rate.ipynb`](notebooks/02_capture_rate.ipynb) — takes the capture rate apart into seasonal and intraday terms, puts the worst year's monthly and hourly price shapes side by side, runs the metered load control, and re-derives the tilt sensitivity.

Both are executed top to bottom by `tests/test_notebooks.py`, so they cannot quietly rot back into two cells that read a CSV.

## Outputs

- `outputs/demo/candidates.gpkg` — candidate-review features with every rule, flag and distance column
- `outputs/demo/quarantine.gpkg` — excluded features and violated rule IDs
- `outputs/demo/site_cards/` — top-three map cards (demo geometry; no aerial claim)
- `outputs/demo/figures/` — proxy comparison, capture-rate, decomposition and seasonal-mismatch figures
- `outputs/demo/capture_rates.csv` — annual ISL0661 results, seasonal/intraday split, flat-profile invariant and metered load control
- `outputs/demo/seasonal_mismatch.csv` — monthly price against modelled output share for the worst year
- `outputs/demo/tilt_sensitivity.csv` — capture rate and December/June output ratio at 0°, 25° and 35°
- `outputs/demo/shape_exponent_sensitivity.csv` — timing-shape sensitivity at exponents 1.0, 1.15 and 1.3
- `outputs/demo/solar_time_basis_comparison.csv` — old civil-clock versus corrected solar-time results
- `outputs/demo/market_year_accounting.csv` — UTC-year and NZ-market-year row reconciliation
- `outputs/demo/run_manifest.json` and `findings.json` — machine-readable provenance and dashboard payload
- `outputs/osm/osm_grid_distance.csv` and `osm_grid_study.json` — the real-geometry grid-proxy comparison over 2,356 OSM farmland polygons
- `outputs/osm/aerial_review_queue.csv` — the twenty largest disagreements with coordinates, a LINZ Basemaps link, the terrain and water columns, and the completed aerial verdicts
- `data/aerial/` — the imagery each verdict was written from, one file per reviewed site
- `data/derived/osm/site_terrain.csv` — per-site mean and p90 slope from Copernicus GLO-30
- `outputs/osm/osm_grid_disagreement.png` — proxy scatter and the top-N agreement sweep

## Demo versus real data

The committed spatial outputs under `outputs/demo/` are deliberately marked `DEMO`: deterministic NZTM geometries exercise every code path without redistributing portal-controlled datasets or making parcel claims. They are not Canterbury candidate parcels. Replace them with the documented LRIS/LINZ/DOC layers to make a full real-data run.

`outputs/osm/` is different: it runs the geometric rules and the grid-distance comparison on real OpenStreetMap geometry, and its numbers are measurements rather than illustrations — subject to the OSM caveats set out above. See [the OSM study](#measuring-the-grid-proxy-disagreement-on-real-geometry).

The market series are different: both the ISL0661 half-hourly final prices and the ISL0661 metered grid-exit load are derived from official Electricity Authority monthly CSVs and filtered to that node. The compact, gzip-compressed filtered series are committed so CI can reproduce every published result without a live network dependency; full monthly source files remain excluded.

## Validation

Eighty-six automated tests cover the CRS gate, exclusion and flag rules, both width methods, spatial-indexed nearest distance, the reject-rate gate, the configurable score weights and the absence of grid distance from the score, 46/48/50-period days, UTC uniqueness, committed-input market-year accounting, merge row conservation, January NZDT peak timing, period-midpoint evaluation, tilt geometry against the horizontal-plane limit, the seasonal/intraday identity and its two synthetic edge cases, the metered load control, output-shape sensitivity, zero-output rejection, the flat-output invariant, agreement between `config/assumptions.yml` and the code defaults, the CRS gate on the committed OSM layers, voltage parsing of shared-circuit tags, that the voltage tiers partition every mapped line exactly once, that a 66 kV way is tiered by voltage rather than by its OSM tag, the published rank-correlation ordering across tiers, that the verify flag discriminates instead of firing on everything, the aerial review's completeness and provenance fields, that every logged verdict cites an image that exists on disk, that the DEM join puts the plains under 2° and the peninsula above 15°, the terrain and water exclusion shares, the in-sample rule check against the labelled twenty, that exclusion and flagging are reported separately and account for every labelled failure, that the published scope field lists the rules actually applied, that the second pass is recorded, and top-to-bottom execution of both notebooks.

GitHub Actions runs the complete demo pipeline. It strictly diffs CSV/JSON; because GeoPackage and PNG bytes vary across operating systems, `scripts/verify_reproduced_outputs.py` compares GeoPackages by fields and geometry and applies a bounded pixel-difference check to figures. That script compares against `origin/main` for any output the branch has not changed, so a branch cannot grade its own artifacts; where an output was intentionally changed it says so and falls back to a determinism-only comparison against `HEAD`.

## Licence and attribution

Code is MIT licensed. Source datasets retain their publishers' licences and attribution requirements. The committed OpenStreetMap extract in `data/derived/osm/` and everything derived from it in `outputs/osm/` are © OpenStreetMap contributors under the **ODbL 1.0**. The aerial images in `data/aerial/` are © LINZ and Environment Canterbury, **CC BY 4.0**, redistributed to evidence the review. Elevation is derived from the **Copernicus GLO-30 DEM**, © European Union / ESA, under its free and open licence. Do not redistribute LRIS, LINZ, DOC or Electricity Authority source files without checking the applicable item terms.

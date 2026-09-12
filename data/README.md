# Data acquisition

Full raw files are intentionally excluded from Git. Record every downloaded file in `checksums.sha256` and transform all spatial inputs to EPSG:2193 before screening. The filtered, gzip-compressed ISL0661 series in `data/derived/` is the committed deterministic market input used by CI.

| Input | Publisher / entry point | Access and licence | Retrieved for this repository |
|---|---|---|---|
| LCDB v5.0 | Manaaki Whenua LRIS, layer 104400 | LRIS account; CC BY 4.0 | Workflow documented; not redistributed |
| NZLRI LUC | Manaaki Whenua LRIS | LRIS account; portal terms | Workflow documented; not redistributed |
| LENZ solar radiation | Manaaki Whenua LRIS, layer 48095 | LRIS account; portal terms | Workflow documented; not redistributed |
| Powerlines and roads | LINZ Data Service | LINZ account/API key; CC BY 4.0 | Workflow documented; not redistributed |
| Conservation areas | DOC Open Spatial Data / LINZ | Open data; check item metadata | Workflow documented; not redistributed |
| Regional boundary | LINZ Data Service | CC BY 4.0 | Workflow documented; not redistributed |
| Half-hourly final prices | Electricity Authority Data & Insights | Public CSV | Retrieval script included; demo output identifies status |

## Spatial workflow

1. Export Canterbury-clipped layers as GeoPackage in NZTM2000 / EPSG:2193.
2. Name layers `landcover`, `luc`, `solar`, `powerlines`, `roads`, `conservation`, and `boundary`.
3. Keep the source metadata/README beside each raw file and add a SHA-256 line.
4. Run `solar-screen` or `scripts/reproduce.py`. The loader refuses missing or non-2193 CRS values.

## Electricity prices

The current canonical discovery page is the Electricity Authority **Data & Insights** hub. The old EMI URLs may redirect to the same public Azure-hosted files and remain useful as stable machine-download paths. This was checked on 13 September 2026. `scripts/download_ea_prices.py` downloads monthly official CSVs, filters to `ISL0661`, preserves trading date and period, and creates an unambiguous UTC timestamp. Daylight-saving start/end days contain 46/50 periods respectively; no wall-clock string is used as a join key.

## Demo boundary

`python scripts/reproduce.py --demo` uses deterministic synthetic NZTM geometries so the complete control flow can run without portal credentials. These geometries are visibly labelled **DEMO** in every output and are not statements about real parcels. Real-data claims must be regenerated after supplying the source layers above.

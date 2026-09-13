# Data acquisition

Full raw files are intentionally excluded from Git. Record every downloaded file in `checksums.sha256` and transform all spatial inputs to EPSG:2193 before screening. The filtered, gzip-compressed ISL0661 price and load series in `data/derived/` are the committed deterministic market inputs used by CI.

| Input | Publisher / entry point | Access and licence | Retrieved for this repository |
|---|---|---|---|
| LCDB v5.0 | Manaaki Whenua LRIS, layer 104400 | LRIS account; CC BY 4.0 | Workflow documented; not redistributed |
| NZLRI LUC | Manaaki Whenua LRIS | LRIS account; portal terms | Workflow documented; not redistributed |
| LENZ solar radiation | Manaaki Whenua LRIS, layer 48095 | LRIS account; portal terms | Workflow documented; not redistributed |
| Powerlines and roads | LINZ Data Service | LINZ account/API key; CC BY 4.0 | Workflow documented; not redistributed |
| Conservation areas | DOC Open Spatial Data / LINZ | Open data; check item metadata | Workflow documented; not redistributed |
| Regional boundary | LINZ Data Service | CC BY 4.0 | Workflow documented; not redistributed |
| Half-hourly final prices | Electricity Authority Data & Insights | Public CSV | Retrieval script included; demo output identifies status |
| Half-hourly metered grid export (load) | Electricity Authority Data & Insights | Public CSV | Retrieval script included; filtered ISL0661 series committed |
| OSM farmland, power lines, road centrelines, water and coastline | OpenStreetMap via Overpass | ODbL 1.0, no account | Canterbury plains extract committed under attribution |
| Copernicus GLO-30 DEM | AWS open-data bucket | Free, no account | Tiles not committed; per-site slope table committed |
| Aerial imagery | LINZ Basemaps | CC BY 4.0 | Review mosaics committed under `data/aerial/` |

## Spatial workflow

1. Export Canterbury-clipped layers as GeoPackage in NZTM2000 / EPSG:2193.
2. Name layers `landcover`, `luc`, `solar`, `powerlines`, `roads`, `conservation`, and `boundary`.
3. Keep the source metadata/README beside each raw file and add a SHA-256 line.
4. Run `solar-screen` or `scripts/reproduce.py`. The loader refuses missing or non-2193 CRS values.

## Electricity prices

The current canonical discovery page is the Electricity Authority **Data & Insights** hub. The old EMI URLs may redirect to the same public Azure-hosted files and remain useful as stable machine-download paths. This was checked on 13 September 2026. `scripts/download_ea_prices.py` downloads monthly official CSVs, filters to `ISL0661`, preserves trading date and period, and creates an unambiguous UTC timestamp. Daylight-saving start/end days contain 46/50 periods respectively; no wall-clock string is used as a join key.

## Load control series

`scripts/download_ea_load.py` downloads the monthly **Grid export** files from the same hub and filters them to `ISL0661`, which is metered energy leaving the grid at that point of connection - that is, local demand at the node the price series already uses. The wide `TP1..TP50` layout is unpivoted onto the same UTC trading-period instants, values for a point of connection are summed across traders, and the trading-date label is normalised because its format changes across the archive. The result is the M3 control shape: a real alternative profile to compare the modelled solar shape against, rather than the flat profile, which is only an arithmetic invariant.

## OpenStreetMap substitute

LINZ Topo50, LCDB and LENZ all need portal accounts, so the grid-distance work ran on hand-drawn rectangles and was only ever a method demonstration. `scripts/download_osm_networks.py` fetches an open substitute with real geometry from Overpass for the Canterbury plains bounding box (`-44.3, 171.3, -43.0, 173.2`): `landuse` farmland/meadow/orchard/vineyard polygons, `power=line` and `power=minor_line` ways, and drivable road centrelines. Output is gzipped GeoJSON in EPSG:2193 with coordinates rounded to 0.1 m and features sorted by OSM id, so the committed extract is byte-stable and CI needs no live network.

**Attribution: (c) OpenStreetMap contributors, data available under the Open Database Licence (ODbL 1.0).** Derived outputs in `outputs/osm/` inherit that licence.

This is a substitute, not the intended source. OSM completeness varies by area and contributor, `power=minor_line` is not the same population as the LINZ powerline layer, and a mapped land-use polygon is a land-use observation rather than a parcel title. `data/aerial_review_log.csv` records the LINZ Basemaps aerial checks done on the largest disagreements, including one polygon that turned out to be a coastal sand spit.

## Terrain

`scripts/compute_site_terrain.py` derives slope for every OSM site that passes the area and width rules, from the Copernicus GLO-30 DEM served as cloud-optimised GeoTIFF from a public bucket. It needs no account. Slope is computed on the 1-arcsecond grid with the degree spacing converted to metres at each tile's latitude, then averaged inside the polygon.

The DEM tiles are about 90 MB for this study area and are **not committed**; they land in `data/raw/copernicus_dem/`, which is gitignored. What is committed is `data/derived/osm/site_terrain.csv` - site id, DEM tile, sample count, mean and 90th-percentile slope - a few tens of kilobytes, and all the screening rule needs. That is why the terrain step is not part of CI while the study that consumes it is.

GLO-30 is a surface model, so shelterbelts and buildings inflate slope locally. S-08 therefore uses the mean over the polygon rather than the maximum, and it is a terrain screen rather than a civil design input.

## Demo boundary

`python scripts/reproduce.py --demo` uses deterministic synthetic NZTM geometries so the complete control flow can run without portal credentials. These geometries are visibly labelled **DEMO** in every output and are not statements about real parcels. Real-data claims must be regenerated after supplying the source layers above.

"""Derive per-site slope from the Copernicus GLO-30 DEM.

The aerial review found that five of the eleven non-developable sites in the
sample failed on terrain alone, and S-08 slope was documented as "not
implemented". This closes that gap with the cheapest open input available:
Copernicus GLO-30 is free, needs no account, and is served as cloud-optimised
GeoTIFF from a public bucket.

It works on any screened polygon layer with a ``site_id`` column, so the real
LCDB run gets the same terrain rules as the OpenStreetMap study: pass ``--sites``
the GeoPackage that ``scripts/build_real_sites.py`` writes. With no ``--sites``
it defaults to the committed OSM extract and applies the area and width rules
itself.

The DEM tiles themselves are large and are not committed. What is committed is
the derived per-site table: mean and 90th-percentile slope in degrees, and the
sample count, for every OSM polygon that passes the area and width rules. That
is a few tens of kilobytes and is all the screening rule needs.

Slope is computed on the 1-arcsecond grid in its own projection, converting the
degree spacing to metres at each tile's latitude, then averaged inside the
polygon. It is a terrain screen, not a civil design input: GLO-30 is a surface
model, so shelterbelts and buildings inflate slope locally, which is why the
rule uses the mean rather than the maximum.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds

from nz_solar_siting.geometry import area_hectares, geometry_sha256, has_width_core
from nz_solar_siting.load import read_layer
from nz_solar_siting.osm_layers import read_osm_layer
from nz_solar_siting.siting import SitingConfig

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
TILE = "{stem}/{stem}.tif"


def tile_stem(lat: int, lon: int) -> str:
    """Copernicus tile name for the 1 degree cell whose south-west corner is given."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def fetch_tile(lat: int, lon: int, cache: Path) -> Path | None:
    stem = tile_stem(lat, lon)
    path = cache / f"{stem}.tif"
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    url = f"{BUCKET}/{TILE.format(stem=stem)}"
    request = Request(url, headers={"User-Agent": "nz-solar-siting-screen terrain screen"})
    try:
        with urlopen(request, timeout=600) as response:
            path.write_bytes(response.read())
    except HTTPError as error:
        if error.code == 404:
            print(f"  no tile at {stem} (ocean)", flush=True)
            return None
        raise
    print(f"  {stem} {path.stat().st_size / 1e6:.0f} MB", flush=True)
    return path


def required_tiles(bounds: pd.DataFrame) -> list[tuple[int, int]]:
    """Every 1 degree tile any polygon touches, not just its two corners.

    The previous version took each polygon's south-west and north-east corner.
    That is the whole set only while a polygon crosses at most one tile line: a
    bounding box that crosses a parallel *and* a meridian sits in four tiles and
    the diagonal names two of them, so the other two were never downloaded and
    the part of the polygon inside them was never sampled. A box wider than a
    degree skips whole tiles in the middle for the same reason.

    Both cases are out of reach for a Canterbury parcel against 1 degree tiles,
    which is why nothing caught this. It is wrong for a larger study area or a
    finer tiling, and the full range costs nothing to enumerate.
    """
    tiles: set[tuple[int, int]] = set()
    for miny, minx, maxy, maxx in zip(
        bounds["miny"], bounds["minx"], bounds["maxy"], bounds["maxx"]
    ):
        if not all(math.isfinite(value) for value in (miny, minx, maxy, maxx)):
            continue
        for lat in range(int(math.floor(miny)), int(math.floor(maxy)) + 1):
            for lon in range(int(math.floor(minx)), int(math.floor(maxx)) + 1):
                tiles.add((lat, lon))
    return sorted(tiles)


def slope_degrees(elevation: np.ndarray, transform, latitude_deg: float) -> np.ndarray:
    """Slope magnitude in degrees on a geographic grid."""
    metres_per_degree_lat = 111_132.0
    metres_per_degree_lon = 111_320.0 * math.cos(math.radians(latitude_deg))
    spacing_y = abs(transform.e) * metres_per_degree_lat
    spacing_x = abs(transform.a) * metres_per_degree_lon
    dy, dx = np.gradient(elevation.astype("float64"), spacing_y, spacing_x)
    return np.degrees(np.arctan(np.hypot(dx, dy)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=None, help="Directory for downloaded DEM tiles")
    parser.add_argument("--output", default="data/derived/osm/site_terrain.csv")
    parser.add_argument(
        "--sites",
        help=(
            "Polygon layer with a site_id column, e.g. the GeoPackage that "
            "scripts/build_real_sites.py writes. Defaults to the committed OSM "
            "farmland extract, which is then filtered by the area and width rules."
        ),
    )
    parser.add_argument("--layer", help="Layer name inside --sites, when the file holds several")
    arguments = parser.parse_args()
    cache = Path(arguments.cache) if arguments.cache else ROOT / "data" / "raw" / "copernicus_dem"
    cache.mkdir(parents=True, exist_ok=True)

    siting = yaml.safe_load((ROOT / "config" / "assumptions.yml").read_text(encoding="utf-8"))["siting"]
    config = SitingConfig(
        minimum_area_ha=float(siting["minimum_area_ha"]),
        minimum_average_width_m=float(siting["minimum_average_width_m"]),
    )

    if arguments.sites:
        # A layer that has already been screened carries its own site_id and has
        # had the area and width rules applied; do not re-filter it.
        sites = read_layer(arguments.sites, ("site_id",), "sites", layer=arguments.layer)
        sites = sites[["site_id", "geometry"]].copy()
    else:
        farmland = read_osm_layer("farmland", ROOT / "data" / "derived" / "osm")
        sites = farmland.copy()
        sites["area_ha"] = sites.geometry.map(area_hectares)
        sites = sites.loc[sites["area_ha"] >= config.minimum_area_ha]
        sites = sites.loc[
            sites.geometry.map(lambda g: has_width_core(g, config.minimum_average_width_m))
        ].copy()
        sites["site_id"] = "OSM-" + sites["osm_id"].astype("int64").astype(str)
    if sites["site_id"].duplicated().any():
        raise ValueError("site_id must be unique; the terrain table is keyed on it")
    sites = sites.sort_values("site_id").reset_index(drop=True)
    geographic = sites.to_crs("EPSG:4326")
    print(f"{len(sites)} sites passing area and width", flush=True)

    needed = required_tiles(geographic.geometry.bounds)
    print(f"DEM tiles required: {len(needed)}", flush=True)

    records: list[dict[str, object]] = []
    for lat, lon in needed:
        path = fetch_tile(lat, lon, cache)
        if path is None:
            continue
        with rasterio.open(path) as dataset:
            # Read masked so the tile's own NoData value does not become an
            # elevation. A void neighbouring real ground would otherwise produce
            # a cliff, and a cliff is exactly what S-08 excludes on.
            elevation = dataset.read(1, masked=True)
            valid = ~np.ma.getmaskarray(elevation)
            gradient = slope_degrees(elevation.filled(np.nan), dataset.transform, lat + 0.5)
            left, bottom, right, top = dataset.bounds
            inside = geographic.cx[left:right, bottom:top]
            for index, geometry in zip(inside.index, inside.geometry):
                window = from_bounds(*geometry.bounds, transform=dataset.transform)
                row_off = max(0, int(math.floor(window.row_off)))
                col_off = max(0, int(math.floor(window.col_off)))
                rows = min(gradient.shape[0] - row_off, int(math.ceil(window.height)) + 1)
                cols = min(gradient.shape[1] - col_off, int(math.ceil(window.width)) + 1)
                if rows <= 0 or cols <= 0:
                    continue
                patch = gradient[row_off:row_off + rows, col_off:col_off + cols]
                patch_transform = dataset.window_transform(
                    rasterio.windows.Window(col_off, row_off, cols, rows)
                )
                mask = ~geometry_mask(
                    [geometry], out_shape=patch.shape, transform=patch_transform,
                    invert=False, all_touched=True,
                )
                patch_valid = valid[row_off:row_off + rows, col_off:col_off + cols]
                values = patch[mask & patch_valid]
                values = values[np.isfinite(values)]
                if values.size == 0:
                    continue
                records.append({
                    "site_id": sites.at[index, "site_id"],
                    "dem_tile": tile_stem(lat, lon),
                    "samples": values,
                })


    # A polygon straddling a tile boundary is sampled once per tile. Keeping
    # only the better-sampled row would report the mean of the larger fragment
    # as the mean of the site; pooling the samples measures the whole polygon.
    pooled: dict[str, dict[str, object]] = {}
    for record in records:
        entry = pooled.setdefault(
            record["site_id"], {"site_id": record["site_id"], "tiles": [], "samples": []}
        )
        entry["tiles"].append(record["dem_tile"])
        entry["samples"].append(record["samples"])
    digests = dict(zip(sites["site_id"], sites.geometry.map(geometry_sha256)))
    rows = []
    for entry in pooled.values():
        values = np.concatenate(entry["samples"])
        rows.append({
            "site_id": entry["site_id"],
            # The geometry the slope was actually averaged over, so the screen
            # can check the join rather than trust the identifier alone.
            "geometry_sha256": digests[entry["site_id"]],
            "dem_tile": ";".join(sorted(set(entry["tiles"]))),
            "dem_tiles_used": len(set(entry["tiles"])),
            "slope_samples": int(values.size),
            "mean_slope_deg": float(values.mean()),
            "p90_slope_deg": float(np.percentile(values, 90)),
        })
    terrain = pd.DataFrame(rows).sort_values("site_id").reset_index(drop=True)
    missing = sorted(set(sites["site_id"]) - set(terrain["site_id"]))
    if missing:
        print(f"warning: no DEM samples for {len(missing)} sites, e.g. {missing[:3]}")
    terrain = terrain.round({"mean_slope_deg": 3, "p90_slope_deg": 3})
    output = ROOT / arguments.output
    terrain.to_csv(output, index=False)
    straddling = int((terrain["dem_tiles_used"] > 1).sum())
    print(f"sites sampled across more than one DEM tile: {straddling}")
    print(terrain["mean_slope_deg"].describe().round(2).to_string())
    print(f"wrote {output} ({len(terrain)} rows)")


if __name__ == "__main__":
    main()

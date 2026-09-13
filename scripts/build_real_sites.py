"""Assemble the real-data screening inputs from LRIS and LINZ.

``solar-screen --sites`` has always accepted real preprocessed layers; what the
repository lacked was the step that produces them. This script is that step.

It pulls the documented layers from the two Koordinates-based portals over WFS,
clips them to the study bounding box, projects everything to EPSG:2193, and
assembles one GeoPackage whose ``sites`` layer carries the four attributes the
screen requires: ``site_id``, ``lcdb_class``, ``luc_class`` and
``solar_kwh_m2``. LCDB polygons of the configured usable classes become the
candidate polygons; LUC class and solar resource are attached by point-in-polygon
lookup on each candidate's representative point.

**Credentials.** LRIS and LINZ both need a free account and an API key, which
only the account holder can create. Supply them as ``LRIS_API_KEY`` and
``LINZ_API_KEY``. Without them this script stops immediately and tells you which
one is missing; nothing here can be run on the author's behalf.

**Layer identifiers.** Portal layer ids change when a publisher reissues a
dataset, so every id lives in ``config/assumptions.yml`` under ``real_data``.
The script prints the title the service returns for each id before downloading,
so pointing at the wrong layer is visible in the first line of output rather
than in the results.

This path has been exercised against recorded fixtures, not against the live
services: see ``tests/test_real_sites.py``. Treat the first live run as a
verification run and check the printed layer titles and feature counts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import pandas as pd

from nz_solar_siting.config import load_project_config
from nz_solar_siting.load import assert_nztm

PAGE_SIZE = 5000


class MissingCredential(RuntimeError):
    """Raised when a portal API key is not present in the environment."""


def api_key(variable: str) -> str:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise MissingCredential(
            f"{variable} is not set. Register a free account, create an API key and export it. "
            "LRIS: https://lris.scinfo.org.nz  LINZ: https://data.linz.govt.nz"
        )
    return value


def _request(url: str, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "nz-solar-siting-screen real-data assembly"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def describe_layer(service: str, key: str, layer_id: int, timeout: int) -> str:
    """Return the service's own title for a layer id, so a wrong id is obvious."""
    query = urlencode({
        "service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
        "typeNames": f"layer-{layer_id}", "outputFormat": "application/json",
    })
    try:
        payload = json.loads(_request(f"{service};key={key}/wfs?{query}", timeout))
    except (HTTPError, ValueError):
        return "unknown (DescribeFeatureType unavailable)"
    types = payload.get("featureTypes") or []
    return str(types[0].get("typeName", "unknown")) if types else "unknown"


def fetch_layer(
    service: str, key: str, layer_id: int, bbox: tuple[float, float, float, float], timeout: int
) -> gpd.GeoDataFrame:
    """Download one WFS layer inside the bounding box, paging until exhausted."""
    frames: list[gpd.GeoDataFrame] = []
    start = 0
    while True:
        query = urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": f"layer-{layer_id}", "outputFormat": "application/json",
            "srsName": "EPSG:2193",
            "bbox": ",".join(f"{value:.1f}" for value in bbox) + ",EPSG:2193",
            "count": PAGE_SIZE, "startIndex": start,
        })
        payload = json.loads(_request(f"{service};key={key}/wfs?{query}", timeout))
        features = payload.get("features") or []
        if not features:
            break
        frames.append(gpd.GeoDataFrame.from_features(features, crs="EPSG:2193"))
        print(f"    +{len(features)} features (from {start})", flush=True)
        if len(features) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    if not frames:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:2193")
    combined = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:2193")


def first_present(frame: gpd.GeoDataFrame, candidates: tuple[str, ...], label: str) -> str:
    """Resolve an attribute name across publisher spellings, or say what is there."""
    lookup = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise KeyError(
        f"{label}: none of {candidates} found. Available columns: {sorted(frame.columns)}"
    )


def attach_by_point(
    sites: gpd.GeoDataFrame, source: gpd.GeoDataFrame, column: str, new_name: str
) -> pd.Series:
    """Look up a source attribute at each site's representative point.

    A representative point is guaranteed to fall inside its own polygon, which a
    centroid is not for concave shapes, so the join cannot silently pick up a
    neighbouring polygon's value.
    """
    points = sites.copy()
    points["geometry"] = sites.geometry.representative_point()
    joined = gpd.sjoin(
        points[["geometry"]], source[[column, "geometry"]], how="left", predicate="within"
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined[column].reindex(sites.index).rename(new_name)


def build_sites(
    landcover: gpd.GeoDataFrame,
    luc: gpd.GeoDataFrame,
    solar: gpd.GeoDataFrame,
    usable_classes: tuple[str, ...],
    minimum_area_ha: float,
    config: dict,
) -> gpd.GeoDataFrame:
    """Turn LCDB polygons into screening sites with the four required attributes."""
    class_column = first_present(landcover, tuple(config["landcover_class_fields"]), "landcover")
    sites = landcover[[class_column, "geometry"]].copy()
    sites = sites.rename(columns={class_column: "lcdb_class"})
    sites["lcdb_class"] = sites["lcdb_class"].astype(str).str.strip()
    sites = sites.loc[sites["lcdb_class"].isin(usable_classes)].copy()
    # LCDB ships multipart polygons; the area and width rules are about one
    # contiguous block of land, so split before measuring anything.
    sites = sites.explode(index_parts=False).reset_index(drop=True)
    sites = sites.loc[sites.geometry.geom_type == "Polygon"].copy()
    sites["geometry"] = sites.geometry.buffer(0)
    sites = sites.loc[~sites.geometry.is_empty].reset_index(drop=True)
    sites = sites.loc[sites.geometry.area >= minimum_area_ha * 10_000.0].reset_index(drop=True)

    luc_column = first_present(luc, tuple(config["luc_class_fields"]), "luc")
    solar_column = first_present(solar, tuple(config["solar_value_fields"]), "solar")
    sites["luc_class"] = pd.to_numeric(
        attach_by_point(sites, luc, luc_column, "luc_class"), errors="coerce"
    )
    sites["solar_kwh_m2"] = pd.to_numeric(
        attach_by_point(sites, solar, solar_column, "solar_kwh_m2"), errors="coerce"
    )
    # A site with no LUC or no solar value cannot be screened by S-05 or S-07.
    # Dropping it silently would hide a join failure, so report and quarantine.
    incomplete = sites["luc_class"].isna() | sites["solar_kwh_m2"].isna()
    if incomplete.any():
        print(
            f"  {int(incomplete.sum())} of {len(sites)} polygons have no LUC or solar value "
            "and are written to sites_unattributed for inspection",
            flush=True,
        )
    # Identifiers must not depend on the order the service happened to page
    # features back, or a re-download would renumber every site. Sort on the
    # geometry's own south-west corner, which is a property of the land.
    bounds = sites.geometry.bounds
    sites = sites.assign(_x=bounds["minx"].round(1), _y=bounds["miny"].round(1))
    sites = sites.sort_values(["_x", "_y", "lcdb_class"], kind="stable").reset_index(drop=True)
    sites = sites.drop(columns=["_x", "_y"])
    sites["site_id"] = [f"LCDB-{index:06d}" for index in range(len(sites))]
    return gpd.GeoDataFrame(
        sites[["site_id", "lcdb_class", "luc_class", "solar_kwh_m2", "geometry"]],
        geometry="geometry", crs="EPSG:2193",
    )


def write_layer(frame: gpd.GeoDataFrame, path: Path, layer: str) -> int:
    path.unlink(missing_ok=True)
    frame.to_file(path, layer=layer, driver="GPKG")
    return int(len(frame))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/assumptions.yml")
    parser.add_argument("--output", default="data/derived/real")
    parser.add_argument("--timeout", type=int, default=300)
    arguments = parser.parse_args()

    project = load_project_config(ROOT / arguments.config)
    settings = project.assumptions["real_data"]
    layers = settings["layers"]
    bbox = tuple(float(value) for value in settings["bbox_nztm"])
    usable = project.siting.usable_lcdb_classes
    output = ROOT / arguments.output
    output.mkdir(parents=True, exist_ok=True)

    services = {
        "lris": (settings["lris_service"], api_key("LRIS_API_KEY")),
        "linz": (settings["linz_service"], api_key("LINZ_API_KEY")),
    }

    downloaded: dict[str, gpd.GeoDataFrame] = {}
    for name, spec in layers.items():
        service, key = services[spec["portal"]]
        layer_id = int(spec["layer_id"])
        title = describe_layer(service, key, layer_id, arguments.timeout)
        print(f"  {name}: layer-{layer_id} -> {title}", flush=True)
        frame = fetch_layer(service, key, layer_id, bbox, arguments.timeout)
        if frame.empty:
            raise RuntimeError(
                f"{name}: layer-{layer_id} returned no features in the study bbox. "
                "Check the layer id on the portal page and the bbox in the config."
            )
        assert_nztm(frame, name)
        downloaded[name] = frame
        print(f"  {name}: {len(frame)} features", flush=True)

    sites = build_sites(
        downloaded["landcover"], downloaded["luc"], downloaded["solar"],
        usable, project.siting.minimum_area_ha, settings,
    )
    complete = sites.dropna(subset=["luc_class", "solar_kwh_m2"]).reset_index(drop=True)
    unattributed = sites.loc[~sites["site_id"].isin(complete["site_id"])]

    # One file per layer, so the existing solar-screen CLI takes them as they are.
    written = {"sites": write_layer(complete, output / "sites.gpkg", "sites")}
    if not unattributed.empty:
        written["sites_unattributed"] = write_layer(
            unattributed, output / "sites_unattributed.gpkg", "sites_unattributed"
        )
    for name in ("conservation", "powerlines", "roads"):
        written[name] = write_layer(downloaded[name], output / f"{name}.gpkg", name)

    relative = output.relative_to(ROOT).as_posix()
    print(json.dumps({
        "output_directory": relative,
        "layers": written,
        "candidate_polygons": int(len(complete)),
        "unattributed_polygons": int(len(unattributed)),
        "usable_lcdb_classes": list(usable),
        "next": (
            f"solar-screen --sites {relative}/sites.gpkg "
            f"--conservation {relative}/conservation.gpkg "
            f"--powerlines {relative}/powerlines.gpkg "
            f"--roads {relative}/roads.gpkg --output outputs/real"
        ),
    }, indent=2))


if __name__ == "__main__":
    main()

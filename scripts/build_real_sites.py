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
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from nz_solar_siting.config import load_project_config
from nz_solar_siting.load import assert_nztm

PAGE_SIZE = 5000


class MissingCredential(RuntimeError):
    """Raised when a portal API key is absent, or is obviously not a key."""


class ServiceError(RuntimeError):
    """Raised when a portal rejects or fails a request, with what to check."""


KEY_PAGES = {
    "LRIS_API_KEY": "https://lris.scinfo.org.nz/my/api/",
    "LINZ_API_KEY": "https://data.linz.govt.nz/my/api/",
}
# The documentation's own example strings. Pasting the example verbatim is the
# most likely way to end up with a set-but-useless variable, and a 400 from the
# service is a poor way to find that out.
PLACEHOLDERS = {"your-lris-key", "your-linz-key", "your-key", "...", "changeme"}


def api_key(variable: str) -> str:
    value = os.environ.get(variable, "").strip()
    page = KEY_PAGES.get(variable, "the portal's API key page")
    if not value:
        raise MissingCredential(
            f"{variable} is not set. Register a free account, create an API key at {page} "
            f"and export it."
        )
    if value.lower() in PLACEHOLDERS:
        raise MissingCredential(
            f"{variable} is set to the example placeholder {value!r}, not a real key. "
            f"Copy the key from {page}."
        )
    if len(value) < 20:
        raise MissingCredential(
            f"{variable} is {len(value)} characters, which is shorter than any key these "
            f"portals issue. Copy the key from {page}."
        )
    return value


def _request(url: str, timeout: int, layer: str = "") -> bytes:
    request = Request(url, headers={"User-Agent": "nz-solar-siting-screen real-data assembly"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        # The URL carries the key, so it must never appear in a message.
        hint = {
            400: "the service rejected the request; the usual cause is a malformed API key, "
                 "then a layer id that is not a WFS feature type",
            401: "the API key was not accepted",
            403: "the API key is not authorised for this layer; accept the licence on the "
                 "layer's portal page, then retry",
            404: "no such layer id on this portal",
            429: "rate limited; wait and retry",
        }.get(error.code, "unexpected response")
        raise ServiceError(
            f"{layer or 'request'} failed: HTTP {error.code} {error.reason} - {hint}"
        ) from None
    except URLError as error:
        raise ServiceError(f"{layer or 'request'} failed: {error.reason}") from None


def describe_layer(service: str, key: str, layer_id: int, timeout: int) -> str:
    """Return the service's own title for a layer id, so a wrong id is obvious."""
    query = urlencode({
        "service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
        "typeNames": f"layer-{layer_id}", "outputFormat": "application/json",
    })
    try:
        payload = json.loads(_request(f"{service};key={key}/wfs?{query}", timeout, f"layer-{layer_id}"))
    except (ServiceError, ValueError):
        return "unknown (DescribeFeatureType unavailable)"
    types = payload.get("featureTypes") or []
    return str(types[0].get("typeName", "unknown")) if types else "unknown"


def fetch_layer(
    service: str, key: str, layer_id: int, bbox: tuple[float, float, float, float],
    timeout: int, attribute_filter: str | None = None,
) -> gpd.GeoDataFrame:
    """Download one WFS layer inside the bounding box, paging until exhausted.

    An ``attribute_filter`` is combined with the bounding box into one CQL
    expression, because this service rejects a ``bbox`` parameter and a
    ``cql_filter`` in the same request.
    """
    frames: list[gpd.GeoDataFrame] = []
    start = 0
    box = "BBOX(shape, {:.1f},{:.1f},{:.1f},{:.1f},'EPSG:2193')".format(*bbox)
    while True:
        parameters = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": f"layer-{layer_id}", "outputFormat": "application/json",
            "srsName": "EPSG:2193",
            "count": PAGE_SIZE, "startIndex": start,
        }
        if attribute_filter:
            parameters["cql_filter"] = f"{attribute_filter} AND {box}"
        else:
            parameters["bbox"] = ",".join(f"{value:.1f}" for value in bbox) + ",EPSG:2193"
        query = urlencode(parameters)
        payload = json.loads(
            _request(f"{service};key={key}/wfs?{query}", timeout, f"layer-{layer_id}")
        )
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


def fetch_protected_area_parcels(
    service: str, key: str, table_id: int, napalis_ids: list[int], timeout: int,
    chunk: int = 200,
) -> pd.DataFrame:
    """The parcels each protected area is made of, from LINZ table 3561.

    This is the layer that makes S-04 an identity test. LINZ says of Protected
    Areas that "the boundaries for most protected areas are derived from the
    Landonline Primary Parcel(s)", so asking the question with geometry measures
    the residual between two renderings of the same boundary. The association is
    published, so it is read rather than inferred.

    The table has no geometry and so no bounding box to filter on; it is
    requested by the napalis ids actually present in the study area, in chunks,
    because the whole table is national.
    """
    rows: list[dict[str, int]] = []
    for start in range(0, len(napalis_ids), chunk):
        batch = napalis_ids[start:start + chunk]
        query = urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": f"table-{table_id}", "outputFormat": "application/json",
            "count": PAGE_SIZE,
            "cql_filter": "napalis_id IN (" + ",".join(str(i) for i in batch) + ")",
        })
        payload = json.loads(
            _request(f"{service};key={key}/wfs?{query}", timeout, f"table-{table_id}")
        )
        rows.extend(feature["properties"] for feature in payload.get("features") or [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["napalis_id", "parcel_id"])
    return (
        frame[["napalis_id", "parcel_id"]]
        .astype("int64")
        .drop_duplicates()
        .sort_values(["napalis_id", "parcel_id"])
        .reset_index(drop=True)
    )


class MissingRasterExport(RuntimeError):
    """Raised when a raster-only layer has not been exported yet."""


def sample_raster(sites: gpd.GeoDataFrame, path: Path, spec: dict, label: str) -> pd.Series:
    """Mean raster value inside each polygon, in annual kWh/m2.

    Some LRIS layers are grids, and a grid has no WFS feature type: the portal
    serves rendered WMTS tiles, whose pixels are palette colours rather than
    measurements. Reading a value therefore needs the raster itself, exported
    once from the layer page.

    Windows are read from disk one polygon at a time. The national LENZ grid is
    23,180 x 24,362 cells, so reading the whole band would cost about a gigabyte
    of memory to answer questions about a few thousand small polygons.
    """
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, from_bounds

    scale = float(spec.get("raster_scale", 1.0))
    per_year = float(spec.get("days_per_year", 1.0)) / float(spec.get("megajoules_per_kwh", 1.0))
    with rasterio.open(path) as dataset:
        if dataset.crs is None:
            raise MissingRasterExport(f"{label}: {path} has no CRS")
        frame = sites.to_crs(dataset.crs)
        values = []
        for geometry in frame.geometry:
            window = from_bounds(*geometry.bounds, transform=dataset.transform)
            row = max(0, int(window.row_off))
            col = max(0, int(window.col_off))
            height = min(dataset.height - row, int(window.height) + 1)
            width = min(dataset.width - col, int(window.width) + 1)
            if height <= 0 or width <= 0:
                values.append(float("nan"))
                continue
            read_window = Window(col, row, width, height)
            patch = dataset.read(1, window=read_window, masked=True)
            mask = ~geometry_mask(
                [geometry], out_shape=patch.shape,
                transform=dataset.window_transform(read_window),
                invert=False, all_touched=True,
            )
            selected = patch[mask & ~patch.mask]
            values.append(float(selected.mean()) if selected.size else float("nan"))
    return pd.Series(values, index=sites.index, dtype=float) * scale * per_year


def class_code(label: object) -> str:
    """Initials of a land-cover class, for a readable identifier."""
    words = [word for word in str(label).replace("-", " ").replace(",", " ").split() if word]
    return "".join(word[0] for word in words).upper() or "X"


def geometry_fingerprint(geometry, precision_m: float = 0.01, length: int = 8) -> str:
    """A stable short hash of a polygon, to 1 cm.

    Coordinates are rounded before hashing so that re-downloading the same
    parcel does not produce a different identifier over floating-point noise.
    Rounding happens in the text form rather than through a precision model,
    which cannot alter the topology of the polygon on the way.
    """
    return hashlib.sha1(
        shapely.to_wkt(geometry, rounding_precision=2, trim=True).encode("utf-8")
    ).hexdigest()[:length]


def site_identifiers(sites: gpd.GeoDataFrame) -> list[str]:
    """Identify a unit by what it is, not by where it landed in the queue.

    A unit is one parcel intersected with one cover class, so the parcel id and
    the class name identify it and the geometry hash separates the pieces when
    that intersection is not connected. Nothing here depends on the order the
    service paged features back or on how many units the run happened to
    produce, which a sequential number does: inserting one parcel used to
    renumber every unit after it, so no identifier survived a re-download and
    nothing keyed on one - a terrain table, an aerial verdict - could be reused.
    """
    if "id" not in sites.columns:
        raise KeyError(
            "parcels must carry their LINZ id: it is what S-04 joins on and what "
            "makes a site_id reproducible. Check real_data.layers.parcels.keep_fields."
        )
    return [
        f"PARCEL-{int(parcel_id)}-{class_code(cover)}-{geometry_fingerprint(geometry)}"
        for parcel_id, cover, geometry in zip(
            sites["id"], sites["lcdb_class"], sites.geometry
        )
    ]


def luc_coverage(
    sites: gpd.GeoDataFrame, luc: gpd.GeoDataFrame, luc_column: str
) -> pd.DataFrame:
    """Area-weighted LUC class per unit, and the LUC 1-3 share of it.

    A representative point asks "what class is the middle of this unit", which
    is the wrong question for a rule about how much of a unit is highly
    productive land: a parcel that is 90% LUC 2 with a LUC 6 hollow in the
    middle answered 6. The overlay answers the coverage question, returns the
    class with the most area as the published ``luc_class``, and the LUC 1-3
    share as ``hpl_fraction``.

    The share is a fraction of the unit, so land the LUC layer does not cover at
    all reduces it rather than being silently redistributed.
    """
    pieces = gpd.overlay(
        sites[["site_id", "geometry"]],
        luc[[luc_column, "geometry"]].rename(columns={luc_column: "luc_class"}),
        how="intersection", keep_geom_type=True,
    )
    pieces["luc_class"] = pd.to_numeric(pieces["luc_class"], errors="coerce")
    pieces["piece_m2"] = pieces.geometry.area
    unit_area = pd.Series(sites.geometry.area.to_numpy(), index=sites["site_id"])
    by_class = pieces.groupby(["site_id", "luc_class"], dropna=True)["piece_m2"].sum()
    dominant = by_class.reset_index().sort_values(
        ["site_id", "piece_m2", "luc_class"], ascending=[True, False, True]
    ).drop_duplicates("site_id").set_index("site_id")["luc_class"]
    hpl = (
        by_class.reset_index()
        .loc[lambda frame: frame["luc_class"].isin([1, 2, 3])]
        .groupby("site_id")["piece_m2"].sum()
    )
    mapped = by_class.groupby("site_id").sum()
    return pd.DataFrame({
        "luc_class": dominant.reindex(sites["site_id"]).to_numpy(),
        "hpl_fraction": (hpl.reindex(sites["site_id"]).fillna(0.0)
                         / unit_area.reindex(sites["site_id"])).to_numpy(),
        "luc_mapped_fraction": (mapped.reindex(sites["site_id"]).fillna(0.0)
                                / unit_area.reindex(sites["site_id"])).to_numpy(),
    }, index=sites.index)


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


def usable_cover(
    landcover: gpd.GeoDataFrame, usable_classes: tuple[str, ...], config: dict
) -> gpd.GeoDataFrame:
    class_column = first_present(landcover, tuple(config["landcover_class_fields"]), "landcover")
    cover = landcover[[class_column, "geometry"]].rename(columns={class_column: "lcdb_class"})
    cover["lcdb_class"] = cover["lcdb_class"].astype(str).str.strip()
    return cover.loc[cover["lcdb_class"].isin(usable_classes)].copy()


def intersect_with_parcels(
    cover: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame, keep_fields: list[str]
) -> gpd.GeoDataFrame:
    """Cut usable land cover to parcel boundaries.

    A land-cover polygon is not a thing anyone can buy or lease: LCDB maps cover
    and merges straight across ownership, which is how a single "site" reached
    230,000 ha. The screening unit is the intersection, so an area rule finally
    measures something a developer could negotiate for.
    """
    available = [field for field in keep_fields if field in parcels.columns]
    trimmed = parcels[available + ["geometry"]].copy()
    trimmed["geometry"] = trimmed.geometry.buffer(0)
    cover = cover.copy()
    cover["geometry"] = cover.geometry.buffer(0)
    units = gpd.overlay(trimmed, cover, how="intersection", keep_geom_type=True)
    return units


def build_sites(
    landcover: gpd.GeoDataFrame,
    luc: gpd.GeoDataFrame,
    solar: gpd.GeoDataFrame,
    usable_classes: tuple[str, ...],
    minimum_area_ha: float,
    config: dict,
    parcels: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Turn land cover into screening sites with the four required attributes."""
    cover = usable_cover(landcover, usable_classes, config)
    if parcels is not None:
        sites = intersect_with_parcels(
            cover, parcels, list(config["layers"]["parcels"]["keep_fields"])
        )
    else:
        sites = cover.copy()
    # LCDB ships multipart polygons; the area and width rules are about one
    # contiguous block of land, so split before measuring anything.
    sites = sites.explode(index_parts=False).reset_index(drop=True)
    sites = sites.loc[sites.geometry.geom_type == "Polygon"].copy()
    sites["geometry"] = sites.geometry.buffer(0)
    sites = sites.loc[~sites.geometry.is_empty].reset_index(drop=True)
    sites = sites.loc[sites.geometry.area >= minimum_area_ha * 10_000.0].reset_index(drop=True)

    luc_column = first_present(luc, tuple(config["luc_class_fields"]), "luc")
    if isinstance(solar, gpd.GeoDataFrame):
        solar_column = first_present(solar, tuple(config["solar_value_fields"]), "solar")
        sites["solar_kwh_m2"] = pd.to_numeric(
            attach_by_point(sites, solar, solar_column, "solar_kwh_m2"), errors="coerce"
        )
    else:
        sites["solar_kwh_m2"] = sample_raster(sites, solar, config["layers"]["solar"], "solar")
    # A stable order for the file, and identifiers that do not depend on it.
    bounds = sites.geometry.bounds
    sites = sites.assign(_x=bounds["minx"].round(1), _y=bounds["miny"].round(1))
    sites = sites.sort_values(["_x", "_y", "lcdb_class"], kind="stable").reset_index(drop=True)
    sites = sites.drop(columns=["_x", "_y"])
    if parcels is not None:
        sites["site_id"] = site_identifiers(sites)
        sites["parcel_id"] = pd.to_numeric(sites["id"], errors="coerce").astype("Int64")
    else:
        sites["site_id"] = [
            f"LCDB-{class_code(cover)}-{geometry_fingerprint(geometry)}"
            for cover, geometry in zip(sites["lcdb_class"], sites.geometry)
        ]
    if sites["site_id"].duplicated().any():
        offender = sites.loc[sites["site_id"].duplicated(), "site_id"].iloc[0]
        raise ValueError(f"site_id is not unique: {offender}")
    # LUC by coverage, not by the class under one point. Done after the
    # identifiers exist because the overlay is keyed on site_id.
    coverage = luc_coverage(sites, luc, luc_column)
    sites["luc_class"] = coverage["luc_class"]
    sites["hpl_fraction"] = coverage["hpl_fraction"].round(4)
    sites["luc_mapped_fraction"] = coverage["luc_mapped_fraction"].round(4)
    # A site with no LUC or no solar value cannot be screened by S-05 or S-07.
    # Dropping it silently would hide a join failure, so report and quarantine.
    incomplete = sites["luc_class"].isna() | sites["solar_kwh_m2"].isna()
    if incomplete.any():
        print(
            f"  {int(incomplete.sum())} of {len(sites)} polygons have no LUC or solar value "
            "and are written to sites_unattributed for inspection",
            flush=True,
        )
    columns = ["site_id", "lcdb_class", "luc_class", "solar_kwh_m2",
               "hpl_fraction", "luc_mapped_fraction"]
    if "parcel_id" in sites.columns:
        columns.append("parcel_id")
    # Parcel attributes are carried through for the reviewer: an appellation and
    # a title reference is what turns a polygon into something you can look up.
    columns += [
        field for field in ("appellation", "titles", "parcel_intent", "calc_area")
        if field in sites.columns
    ]
    return gpd.GeoDataFrame(
        sites[columns + ["geometry"]], geometry="geometry", crs="EPSG:2193",
    )


def write_layer(frame: gpd.GeoDataFrame, path: Path, layer: str) -> int:
    path.unlink(missing_ok=True)
    frame.to_file(path, layer=layer, driver="GPKG")
    return int(len(frame))


def preflight(services: dict[str, tuple[str, str]], layers: dict, timeout: int) -> None:
    """Check every layer id answers before downloading any of them.

    A run that dies on the sixth layer after twenty minutes of paging has wasted
    the twenty minutes. One cheap request each says up front whether the keys
    work and whether every id is a real feature type.
    """
    print("preflight:", flush=True)
    problems: list[str] = []
    for name, spec in layers.items():
        if spec.get("source") == "raster_export":
            path = ROOT / spec["raster_path"]
            # Create the directory rather than naming one that does not exist:
            # "save it here" is not useful advice if "here" is missing.
            path.parent.mkdir(parents=True, exist_ok=True)
            state = "present" if path.exists() else "NOT EXPORTED"
            print(f" {' ' if path.exists() else '?'} {name:<12} raster           {state}: "
                  f"{spec['raster_path']}", flush=True)
            if not path.exists():
                problems.append(
                    f"{name} is a grid layer, and LRIS offers no WCS for it, so its values "
                    f"cannot be read over the web services."
                    f"\n    Export it once from {spec['export_page']} as GeoTIFF in EPSG:2193,"
                    f"\n    and save it as exactly this file (the folder now exists):"
                    f"\n      {path}"
                )
            continue
        service, key = services[spec["portal"]]
        layer_id = int(spec["layer_id"])
        title = describe_layer(service, key, layer_id, timeout)
        marker = "?" if title.startswith("unknown") else " "
        print(f" {marker} {name:<12} layer-{layer_id:<7} {title}", flush=True)
        if title.startswith("unknown"):
            problems.append(f"{name} (layer-{layer_id}, {spec['portal']})")
    if problems:
        raise ServiceError(
            "preflight failed:\n  - " + "\n  - ".join(problems)
            + "\nCheck each layer id against its portal page, and accept the licence there "
            "if you have not already."
        )


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
    siting_values = project.assumptions["siting"]
    output = ROOT / arguments.output
    output.mkdir(parents=True, exist_ok=True)

    services = {
        "lris": (settings["lris_service"], api_key("LRIS_API_KEY")),
        "linz": (settings["linz_service"], api_key("LINZ_API_KEY")),
    }

    preflight(services, layers, arguments.timeout)

    basis = str(settings.get("site_basis", "parcel_intersection"))
    downloaded: dict[str, gpd.GeoDataFrame] = {}
    for name, spec in layers.items():
        if spec.get("source") == "raster_export":
            continue
        if name == "parcels" and basis != "parcel_intersection":
            continue
        service, key = services[spec["portal"]]
        layer_id = int(spec["layer_id"])
        attribute_filter = None
        if spec.get("area_filter_from"):
            threshold = float(siting_values[spec["area_filter_from"]]) * 10_000.0
            attribute_filter = f"calc_area > {threshold:.0f}"
        print(f"  {name}: downloading layer-{layer_id}"
              + (f" where {attribute_filter}" if attribute_filter else ""), flush=True)
        frame = fetch_layer(service, key, layer_id, bbox, arguments.timeout, attribute_filter)
        if frame.empty:
            raise RuntimeError(
                f"{name}: layer-{layer_id} returned no features in the study bbox. "
                "Check the layer id on the portal page and the bbox in the config."
            )
        assert_nztm(frame, name)
        downloaded[name] = frame
        print(f"  {name}: {len(frame)} features", flush=True)

    solar_spec = layers["solar"]
    solar_source = (
        ROOT / solar_spec["raster_path"]
        if solar_spec.get("source") == "raster_export"
        else downloaded["solar"]
    )
    sites = build_sites(
        downloaded["landcover"], downloaded["luc"], solar_source,
        usable, project.siting.minimum_area_ha, settings,
        parcels=downloaded.get("parcels"),
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

    association = pd.DataFrame(columns=["napalis_id", "parcel_id"])
    table_id = settings.get("protected_area_parcel_table")
    if table_id and "napalis_id" in downloaded["conservation"].columns:
        napalis_ids = sorted(set(
            pd.to_numeric(downloaded["conservation"]["napalis_id"], errors="coerce")
            .dropna().astype("int64")
        ))
        print(f"  conservation_parcels: table-{table_id} for {len(napalis_ids)} protected areas",
              flush=True)
        service, key = services["linz"]
        association = fetch_protected_area_parcels(
            service, key, int(table_id), napalis_ids, arguments.timeout
        )
        association.to_csv(output / "conservation_parcels.csv", index=False)
        written["conservation_parcels"] = int(len(association))
        covered = association["napalis_id"].nunique() if not association.empty else 0
        print(f"  conservation_parcels: {len(association)} rows covering {covered} of "
              f"{len(napalis_ids)} protected areas", flush=True)

    relative = output.relative_to(ROOT).as_posix()
    print(json.dumps({
        "output_directory": relative,
        "layers": written,
        "candidate_polygons": int(len(complete)),
        "unattributed_polygons": int(len(unattributed)),
        "site_basis": basis,
        "usable_lcdb_classes": list(usable),
        "next": (
            f"solar-screen --sites {relative}/sites.gpkg "
            f"--conservation {relative}/conservation.gpkg "
            f"--powerlines {relative}/powerlines.gpkg "
            f"--roads {relative}/roads.gpkg "
            f"--conservation-parcels {relative}/conservation_parcels.csv "
            f"--output outputs/real"
        ),
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (MissingCredential, ServiceError) as error:
        # These are the user's problems to fix, not stack traces to read.
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(2) from None

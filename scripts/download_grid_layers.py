"""Download the two authoritative powerline layers for the study area.

The grid-distance work has so far had one source of network geometry with a
voltage attribute: OpenStreetMap. Two public layers can check it.

LINZ Topo50 powerline centrelines are the layer the original method named. They
are CC BY and carry no voltage attribute at all, which is the point: a screen
built on them cannot tell a 220 kV circuit from an 11 kV spur.

Transpower publishes its own transmission lines with a ``designvolt`` field,
CC BY, from its open-data hub. It is authoritative for the national grid and
covers nothing below it, so it is both a source for the 110 kV-and-above tier
and a yardstick for how complete OpenStreetMap's transmission mapping is.

Neither needs an account. Topo50 needs the LINZ key the rest of the workflow
already uses; Transpower needs nothing at all.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd

from nz_solar_siting.config import load_project_config

TRANSPOWER = (
    "https://services3.arcgis.com/AkUq3zcWf7TVqyR9/arcgis/rest/services"
    "/TransmissionLines/FeatureServer/0/query"
)
PAGE = 2000


def write(frame: gpd.GeoDataFrame, path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = frame.sort_values(list(frame.columns.drop("geometry"))[0], kind="stable")
    frame = frame.reset_index(drop=True)
    frame["geometry"] = frame.geometry.set_precision(0.1)
    payload = json.loads(frame.to_json(drop_id=True))
    payload["name"] = name
    with gzip.GzipFile(path, "wb", mtime=0) as handle:
        handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    print(f"  {name}: {len(frame)} features -> {path} "
          f"({path.stat().st_size / 1e6:.2f} MB)", flush=True)


def fetch_transpower(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Page the Transpower feature service inside the study bounding box."""
    frames = []
    offset = 0
    while True:
        query = urlencode({
            "where": "1=1", "outFields": "MXLOCATION,designvolt,status,description,type",
            "geometry": ",".join(f"{value:.1f}" for value in bbox),
            "geometryType": "esriGeometryEnvelope", "inSR": "2193",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "2193", "f": "geojson",
            "resultOffset": offset, "resultRecordCount": PAGE,
        })
        request = Request(f"{TRANSPOWER}?{query}", headers={"User-Agent": "nz-solar-siting-screen"})
        with urlopen(request, timeout=300) as response:
            payload = json.loads(response.read().decode("utf-8"))
        features = payload.get("features") or []
        if not features:
            break
        frames.append(gpd.GeoDataFrame.from_features(features, crs="EPSG:2193"))
        if len(features) < PAGE:
            break
        offset += PAGE
    if not frames:
        raise RuntimeError("Transpower returned no features in the study bbox")
    import pandas as pd

    combined = pd.concat(frames, ignore_index=True)
    frame = gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:2193")
    # designvolt arrives as text; the library's voltage parser wants volts.
    frame["voltage"] = (
        frame["designvolt"].astype(str).str.extract(r"(\d+)")[0].astype(float) * 1000.0
    )
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/derived/grid")
    parser.add_argument("--timeout", type=int, default=300)
    arguments = parser.parse_args()

    project = load_project_config(ROOT / "config" / "assumptions.yml")
    settings = project.assumptions["real_data"]
    bbox = tuple(float(value) for value in settings["bbox_nztm"])
    output = ROOT / arguments.output

    print("transpower transmission lines (CC BY, no account):", flush=True)
    transpower = fetch_transpower(bbox)
    write(transpower[["MXLOCATION", "designvolt", "voltage", "status", "geometry"]],
          output / "transpower_lines.geojson.gz", "transpower_lines")
    print("    voltages:", sorted(transpower["designvolt"].dropna().unique().tolist()))

    print("linz topo50 powerline centrelines (CC BY, needs the LINZ key):", flush=True)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_real_sites", ROOT / "scripts" / "build_real_sites.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    key = builder.api_key("LINZ_API_KEY")
    topo = builder.fetch_layer(
        settings["linz_service"], key, int(settings["layers"]["powerlines"]["layer_id"]),
        bbox, arguments.timeout,
    )
    write(topo, output / "topo50_powerlines.geojson.gz", "topo50_powerlines")
    print("    attributes:", sorted(topo.columns.drop("geometry").tolist()))


if __name__ == "__main__":
    main()

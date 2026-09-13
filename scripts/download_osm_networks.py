"""Download OpenStreetMap network and farmland layers for the Canterbury plains.

LINZ Topo50 and LCDB both need portal credentials, so the grid-distance study in
this repository ran on hand-drawn rectangles and was only ever a method
demonstration. OpenStreetMap is open (ODbL) and needs no account, so it supplies
a credential-free substitute with real geometry: mapped farmland polygons, mapped
transmission and distribution lines, and mapped road centrelines.

It is a substitute, not the intended source. OSM completeness is uneven and
varies by area and by contributor; a mapped farmland polygon is a land-use
observation, not a parcel title. Everything derived from these layers is
published as an OSM-based study and kept separate from the LINZ workflow that
``data/README.md`` documents.

Output: gzipped GeoJSON in EPSG:2193 under ``data/derived/osm/``, with
coordinates rounded to 0.1 m and features sorted by OSM id so the committed
files are byte-stable.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
from shapely.geometry import LineString, Polygon

ENDPOINT = "https://overpass-api.de/api/interpreter"
# Canterbury plains: the area the screen is about, and small enough that the
# committed extract stays a few megabytes.
BBOX = (-44.3, 171.3, -43.0, 173.2)

LAYERS = {
    "powerlines": {
        "filters": ['["power"="line"]', '["power"="minor_line"]'],
        "kind": "line",
        "keep": ("power", "voltage", "operator"),
    },
    "roads": {
        "filters": [
            '["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential)$"]'
        ],
        "kind": "line",
        "keep": ("highway", "ref"),
    },
    "farmland": {
        "filters": ['["landuse"~"^(farmland|meadow|orchard|vineyard)$"]'],
        "kind": "area",
        "keep": ("landuse", "crop"),
    },
}


def query(filters: list[str], timeout_s: int) -> dict:
    south, west, north, east = BBOX
    body = (
        f"[out:json][timeout:{timeout_s}];\n(\n"
        + "".join(f'  way{f}({south},{west},{north},{east});\n' for f in filters)
        + ");\nout geom;"
    )
    request = Request(
        ENDPOINT,
        data=body.encode("utf-8"),
        headers={"User-Agent": "nz-solar-siting-screen/0.1 (OSM extract for a public screening demo)"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout_s + 60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == 2:
                raise
            print(f"  retrying after {error}", flush=True)
            time.sleep(30)
    raise RuntimeError("unreachable")


def build(payload: dict, kind: str, keep: tuple[str, ...]) -> gpd.GeoDataFrame:
    records, geometries = [], []
    for element in sorted(payload["elements"], key=lambda e: e.get("id", 0)):
        points = [(node["lon"], node["lat"]) for node in element.get("geometry") or []]
        if kind == "area":
            if len(points) < 4 or points[0] != points[-1]:
                continue
            geometry = Polygon(points)
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            if geometry.is_empty or geometry.geom_type != "Polygon":
                continue
        else:
            if len(points) < 2:
                continue
            geometry = LineString(points)
        tags = element.get("tags", {})
        records.append({"osm_id": element["id"], **{key: tags.get(key) for key in keep}})
        geometries.append(geometry)
    frame = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326").to_crs("EPSG:2193")
    frame["geometry"] = frame.geometry.set_precision(0.1)
    return frame[~frame.geometry.is_empty].reset_index(drop=True)


def write(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(frame.to_json(drop_id=True))
    payload["name"] = path.name.split(".")[0]
    with gzip.GzipFile(path, "wb", mtime=0) as handle:
        handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/derived/osm")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--layer", choices=sorted(LAYERS), action="append")
    arguments = parser.parse_args()
    output = ROOT / arguments.output
    for name in arguments.layer or sorted(LAYERS):
        spec = LAYERS[name]
        print(f"downloading {name}", flush=True)
        frame = build(query(spec["filters"], arguments.timeout), spec["kind"], spec["keep"])
        path = output / f"{name}.geojson.gz"
        write(frame, path)
        print(f"  {len(frame)} features -> {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()

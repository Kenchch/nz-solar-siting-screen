"""Download official EA grid-export (load) data and retain one node only.

The capture-rate work needs a real demand shape at the same node as the price
series, not a stylised evening-peak curve. Electricity Authority "Grid export"
files are half-hourly metered energy leaving the grid at each point of
connection, so filtering to ISL0661 gives the local load shape on exactly the
trading periods the price series uses.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = (
    "https://emidatasets.blob.core.windows.net/publicdata/Datasets/Wholesale/"
    "Metered_data/Grid_export/{yearmonth}_Grid_export.csv"
)
FIELDS = ["trading_date", "trading_period", "timestamp_utc", "load_kwh", "node", "source_month"]


def _iso_date(label: str) -> str:
    """Normalise the trading-date label, which changed format across archives."""
    text = str(label).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unrecognised trading date: {label!r}")


def fetch_month(yearmonth: str, node: str, output_dir: Path, market_timezone: str) -> Path:
    target = output_dir / f"{yearmonth}_{node}_load.csv"
    if target.exists() and target.stat().st_size > 100:
        with target.open("r", encoding="utf-8") as cached:
            if set(FIELDS) <= set(next(csv.reader(cached))):
                return target
    request = Request(
        BASE.format(yearmonth=yearmonth),
        headers={"User-Agent": "nz-solar-siting-screen/0.1"},
    )
    with urlopen(request, timeout=180) as response, tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=output_dir, suffix=".tmp"
    ) as tmp:
        text = (line.decode("utf-8-sig") for line in response)
        reader = csv.DictReader(text)
        writer = csv.DictWriter(tmp, fieldnames=FIELDS)
        writer.writeheader()
        totals: dict[tuple[str, int], float] = {}
        for raw_row in reader:
            row = {str(key).strip().lower(): value for key, value in raw_row.items()}
            if str(row.get("poc", "")).upper() != node.upper():
                continue
            date = _iso_date(row["trading_date"])
            for period in range(1, 51):
                value = row.get(f"tp{period}")
                if value is None or str(value).strip() == "":
                    continue
                key = (date, period)
                totals[key] = totals.get(key, 0.0) + float(value)
        for (date, period), value in sorted(totals.items()):
            local_midnight = datetime.strptime(date, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo(market_timezone)
            )
            instant = local_midnight.astimezone(timezone.utc) + timedelta(
                minutes=(period - 1) * 30
            )
            writer.writerow(
                {
                    "trading_date": date,
                    "trading_period": period,
                    "timestamp_utc": instant.isoformat().replace("+00:00", "Z"),
                    "load_kwh": f"{value:.4f}",
                    "node": node,
                    "source_month": yearmonth,
                }
            )
        temp_path = Path(tmp.name)
    temp_path.replace(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--node", default="ISL0661")
    parser.add_argument("--output", default="data/raw/ea_load")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timezone", default="Pacific/Auckland")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    months = [
        f"{year}{month:02d}"
        for year in range(args.start_year, args.end_year + 1)
        for month in range(1, 13)
    ]
    completed: list[Path] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_month, month, args.node, output, args.timezone): month
            for month in months
        }
        for future in as_completed(futures):
            completed.append(future.result())
            print(f"downloaded {futures[future]}", flush=True)
    combined = output.parent / f"{args.node}_load_{args.start_year}_{args.end_year}.csv"
    with combined.open("w", encoding="utf-8", newline="") as destination:
        wrote_header = False
        for path in sorted(completed):
            with path.open("r", encoding="utf-8") as source:
                header = source.readline()
                if not wrote_header:
                    destination.write(header)
                    wrote_header = True
                for line in source:
                    destination.write(line)
    print(combined)


if __name__ == "__main__":
    main()

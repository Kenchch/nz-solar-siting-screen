"""Download official EA monthly final prices and retain one node only."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

BASE = (
    "https://emidatasets.blob.core.windows.net/publicdata/Datasets/Wholesale/"
    "DispatchAndPricing/FinalEnergyPrices/ByMonth/{filename}"
)


def fetch_month(yearmonth: str, node: str, output_dir: Path) -> Path:
    target = output_dir / f"{yearmonth}_{node}.csv"
    if target.exists() and target.stat().st_size > 100:
        return target
    filename = (
        "202512_FinalEnergyPrices_incomplete.csv"
        if yearmonth == "202512"
        else f"{yearmonth}_FinalEnergyPrices.csv"
    )
    request = Request(BASE.format(filename=filename), headers={"User-Agent": "nz-solar-siting-screen/0.1"})
    with urlopen(request, timeout=90) as response, tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=output_dir, suffix=".tmp"
    ) as tmp:
        text = (line.decode("utf-8-sig") for line in response)
        reader = csv.DictReader(text)
        writer = csv.DictWriter(tmp, fieldnames=["timestamp", "price_nzd_mwh", "node", "source_month"])
        writer.writeheader()
        for row in reader:
            poc = row.get("PointOfConnection") or row.get("Node")
            if str(poc).upper() != node.upper():
                continue
            date = row.get("TradingDate") or row.get("Date")
            period = int(row.get("TradingPeriod") or row.get("Period") or 0)
            price = row.get("DollarsPerMegawattHour") or row.get("Price")
            writer.writerow(
                {
                    "timestamp": f"{date}T{(period - 1) // 2:02d}:{'30' if period % 2 == 0 else '00'}:00",
                    "price_nzd_mwh": price,
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
    parser.add_argument("--output", default="data/raw/ea_prices")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    months = [f"{year}{month:02d}" for year in range(args.start_year, args.end_year + 1) for month in range(1, 13)]
    completed: list[Path] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_month, month, args.node, output): month for month in months}
        for future in as_completed(futures):
            completed.append(future.result())
            print(f"downloaded {futures[future]}", flush=True)
    combined = output.parent / f"{args.node}_{args.start_year}_{args.end_year}.csv"
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

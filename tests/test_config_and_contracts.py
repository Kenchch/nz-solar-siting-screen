import json
from pathlib import Path
import sys

from nz_solar_siting.config import load_project_config
from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting import screen

ROOT = Path(__file__).resolve().parents[1]


def test_demo_cli_uses_the_shared_demo_top_n(monkeypatch, tmp_path):
    config_path = ROOT / "config/assumptions.yml"
    configured = load_project_config(config_path)
    monkeypatch.setattr(sys, "argv", [
        "solar-screen", "--demo", "--config", str(config_path),
        "--output", str(tmp_path),
    ])
    screen.main()
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["grid_comparison"]["n"] == configured.demo_top_n_comparison == 4
    assert manifest["grid_comparison"]["jaccard"] == 0.333


def test_rule_register_matches_width_core_baseline():
    register = (ROOT / "rules/rule_register.csv").read_text(encoding="utf-8")
    s02 = next(line for line in register.splitlines() if line.startswith("S-02,"))
    assert "inward-buffer core" in s02
    assert "2A/P published as audit comparator only" in s02


def test_preprocessed_real_layer_cli_runs(monkeypatch, tmp_path):
    names = ("sites", "conservation", "powerlines", "roads")
    paths = {}
    for name, frame in zip(names, build_demo_layers()):
        path = tmp_path / f"{name}.gpkg"
        frame.to_file(path, layer=name, driver="GPKG")
        paths[name] = path
    output = tmp_path / "real-output"
    monkeypatch.setattr(sys, "argv", [
        "solar-screen", "--sites", str(paths["sites"]),
        "--conservation", str(paths["conservation"]),
        "--powerlines", str(paths["powerlines"]), "--roads", str(paths["roads"]),
        "--config", str(ROOT / "config/assumptions.yml"), "--output", str(output),
    ])
    screen.main()
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["scope"] == "screening only; user-supplied preprocessed spatial layers"
    assert manifest["grid_comparison"]["n"] == 8


def test_dashboard_selects_latest_complete_year():
    javascript = (ROOT / "docs/app.js").read_text(encoding="utf-8")
    assert "find(row => row.complete_year)" in javascript

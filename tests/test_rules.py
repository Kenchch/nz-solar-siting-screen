from dataclasses import replace

import pandas as pd
import pytest

from nz_solar_siting.demo_data import build_demo_layers
from nz_solar_siting.siting import SitingConfig, evaluate_sites


def test_each_exclusion_rule_can_quarantine_for_its_own_reason():
    sites, conservation, powerlines, roads = build_demo_layers()
    results, _ = evaluate_sites(sites, conservation, powerlines, roads)
    observed = set(";".join(results.failed_rule_ids).split(";"))
    assert {"S-01", "S-03", "S-04"} <= observed

    strict = replace(SitingConfig(), minimum_average_width_m=1000.0)
    strict_results, _ = evaluate_sites(sites, conservation, powerlines, roads, strict)
    assert strict_results.failed_rule_ids.str.contains("S-02").any()


def test_luc_1_to_3_is_flag_not_exclusion():
    sites, conservation, powerlines, roads = build_demo_layers()
    results, _ = evaluate_sites(sites, conservation, powerlines, roads)
    flagged_candidates = results[(results.S05_hpl_flag) & (results.status == "candidate_review")]
    assert not flagged_candidates.empty


def test_duplicate_site_ids_are_rejected():
    sites, conservation, powerlines, roads = build_demo_layers()
    sites.loc[sites.index[1], "site_id"] = sites.loc[sites.index[0], "site_id"]
    with pytest.raises(ValueError, match="unique"):
        evaluate_sites(sites, conservation, powerlines, roads)


def test_nonfinite_solar_values_are_rejected():
    sites, conservation, powerlines, roads = build_demo_layers()
    sites.loc[sites.index[0], "solar_kwh_m2"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        evaluate_sites(sites, conservation, powerlines, roads)


def test_quarantined_rows_are_not_ranked_or_scored():
    sites, conservation, powerlines, roads = build_demo_layers()
    results, _ = evaluate_sites(sites, conservation, powerlines, roads)
    excluded = results.status.eq("quarantine")
    assert results.loc[excluded, ["grid_rank", "road_rank", "solar_rank"]].isna().all().all()
    assert pd.isna(results.loc[excluded, "screen_score"]).all()


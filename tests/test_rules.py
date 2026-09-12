from dataclasses import replace

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


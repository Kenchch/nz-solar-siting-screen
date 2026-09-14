"""S-04 and S-05 measure overlap against what the source layers can resolve.

Both rules intersect the screening unit with a layer drawn from somewhere else,
and neither layer knows exactly where the boundary is. The band an overlap has
to clear is ``accuracy x boundary length``, with the accuracy taken from what
the publisher says about the pair - never from the population being screened.

S-04 mostly does not need the band at all: LINZ says the protected-area
boundaries are derived from the parcels, and publishes the association, so the
rule is an identity test and geometry is the fallback for what the table does
not cover.
"""

import math
from dataclasses import replace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from nz_solar_siting.geometry import overlap_noise_band_m2
from nz_solar_siting.siting import SitingConfig, evaluate_sites

X, Y = 1_500_000.0, 5_150_000.0
SIDE = math.sqrt(20 * 10_000)          # a 20 ha square
EMPTY = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:2193")
NETWORK = gpd.GeoDataFrame(
    {"n": [1]},
    geometry=gpd.GeoSeries.from_wkt([f"LINESTRING({X} {Y - 200}, {X + 30000} {Y - 200})"]),
    crs="EPSG:2193",
)


def _sites(**extra) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"site_id": ["A"], "lcdb_class": ["Short-rotation Cropland"],
         "luc_class": [3], "solar_kwh_m2": [1400.0], **extra},
        geometry=[box(X, Y, X + SIDE, Y + SIDE)], crs="EPSG:2193",
    )


def _protected(geometry, napalis_id: int) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"napalis_id": [napalis_id]}, geometry=[geometry], crs="EPSG:2193"
    )


# --------------------------------------------------------------------- S-04

def test_a_parcel_in_the_association_table_is_excluded_without_any_geometry():
    """Identity answers the question geometry was being asked to guess at."""
    sites = _sites(parcel_id=[7_666_945])
    far_away = _protected(box(X + 90_000, Y + 90_000, X + 91_000, Y + 91_000), 2_809_225)
    association = pd.DataFrame({"napalis_id": [2_809_225], "parcel_id": [7_666_945]})
    results, _ = evaluate_sites(
        sites, far_away, NETWORK, NETWORK, conservation_parcels=association
    )
    assert not bool(results["S04_pass"].iloc[0])
    assert results["s04_basis"].iloc[0] == "association"
    assert results["conservation_overlap_m2"].iloc[0] == 0.0


def test_a_sliver_against_an_associated_area_no_longer_excludes():
    """The 1 m2 exclusions: two renderings of one boundary, not an overlap.

    The protected area is in the association table and this parcel is not one of
    its parcels, so the parcel is simply next door. It used to be quarantined on
    the residual between the two renderings.
    """
    sliver = box(X + SIDE - 0.002, Y, X + SIDE + 500, Y + 500)   # about 1 m2
    association = pd.DataFrame({"napalis_id": [2_796_086], "parcel_id": [111]})
    sites = _sites(parcel_id=[222])
    results, _ = evaluate_sites(
        sites, _protected(sliver, 2_796_086), NETWORK, NETWORK,
        conservation_parcels=association,
    )
    assert bool(results["S04_pass"].iloc[0])
    assert results["s04_basis"].iloc[0] == ""


def test_an_area_the_table_does_not_cover_still_falls_back_to_geometry():
    """"most protected areas", not all: marine and non-cadastral areas remain."""
    overlapping = box(X, Y, X + SIDE, Y + 200)      # deep overlap, far above the band
    association = pd.DataFrame({"napalis_id": [2_796_086], "parcel_id": [111]})
    sites = _sites(parcel_id=[222])
    results, _ = evaluate_sites(
        sites, _protected(overlapping, 9_999_999), NETWORK, NETWORK,
        conservation_parcels=association,
    )
    assert not bool(results["S04_pass"].iloc[0])
    assert results["s04_basis"].iloc[0] == "geometry"


def test_the_fallback_still_ignores_an_overlap_inside_its_own_band():
    unassociated = box(X + SIDE - 0.001, Y, X + SIDE + 500, Y + 500)
    association = pd.DataFrame({"napalis_id": [1], "parcel_id": [111]})
    sites = _sites(parcel_id=[222])
    results, _ = evaluate_sites(
        sites, _protected(unassociated, 9_999_999), NETWORK, NETWORK,
        conservation_parcels=association,
    )
    band = results["conservation_noise_band_m2"].iloc[0]
    assert results["conservation_overlap_m2"].iloc[0] < band
    assert bool(results["S04_pass"].iloc[0])


def test_the_reconciliation_between_identity_and_geometry_is_published():
    """The only way to know whether the identity join is trustworthy."""
    sites = _sites(parcel_id=[7_666_945])
    far_away = _protected(box(X + 90_000, Y + 90_000, X + 91_000, Y + 91_000), 2_809_225)
    association = pd.DataFrame({"napalis_id": [2_809_225], "parcel_id": [7_666_945]})
    results, _ = evaluate_sites(
        sites, far_away, NETWORK, NETWORK, conservation_parcels=association
    )
    reconciliation = results.attrs["s04_reconciliation"]
    assert reconciliation["identity_available"] is True
    assert reconciliation["identity_only"] == 1, "identity excluded it, geometry did not"
    assert reconciliation["geometry_only"] == 0


def test_without_the_table_s04_is_geometry_and_says_so():
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK)
    assert results.attrs["s04_reconciliation"] == {"identity_available": False}


# --------------------------------------------------------------------- S-05

def test_the_noise_band_is_the_units_own_and_matches_the_worked_example():
    """A 20 ha square at 32 m carries a band of about 29% of itself."""
    square = box(X, Y, X + SIDE, Y + SIDE)
    band = overlap_noise_band_m2(square, 32.0) / square.area
    assert band == pytest.approx(0.286, abs=0.002)


def test_a_coverage_fraction_inside_the_band_is_not_a_flag():
    """Below its own band, "some LUC 1-3 touches this unit" says nothing."""
    results, _ = evaluate_sites(_sites(hpl_fraction=[0.10]), EMPTY, NETWORK, NETWORK)
    assert results["hpl_fraction"].iloc[0] == 0.10
    assert results["luc_noise_band"].iloc[0] == pytest.approx(0.286, abs=0.002)
    assert not bool(results["S05_hpl_flag"].iloc[0])
    assert results["s05_basis"].iloc[0] == "coverage_fraction"


def test_a_coverage_fraction_above_the_band_is_a_flag():
    results, _ = evaluate_sites(_sites(hpl_fraction=[0.75]), EMPTY, NETWORK, NETWORK)
    assert bool(results["S05_hpl_flag"].iloc[0])


def test_a_long_thin_unit_is_held_to_a_weaker_claim_than_a_compact_one():
    """More boundary to misregister means a wider band, on the same area."""
    compact = box(X, Y, X + SIDE, Y + SIDE)
    thin = box(X, Y, X + 20_000, Y + 10)            # same 20 ha, far more edge
    assert (overlap_noise_band_m2(thin, 32.0) / thin.area) > (
        overlap_noise_band_m2(compact, 32.0) / compact.area
    )


def test_without_a_coverage_fraction_the_flag_falls_back_and_records_it():
    results, _ = evaluate_sites(_sites(), EMPTY, NETWORK, NETWORK)
    assert results["s05_basis"].iloc[0] == "dominant_class"
    assert bool(results["S05_hpl_flag"].iloc[0]), "luc_class 3 is still LUC 1-3"
    assert pd.isna(results["hpl_fraction"].iloc[0])


def test_the_accuracy_bands_are_configurable_and_not_baked_in():
    generous = replace(SitingConfig(), luc_overlay_accuracy_m=0.0)
    results, _ = evaluate_sites(_sites(hpl_fraction=[0.01]), EMPTY, NETWORK, NETWORK, generous)
    assert results["luc_noise_band"].iloc[0] == 0.0
    assert bool(results["S05_hpl_flag"].iloc[0]), "with no band, any coverage flags"

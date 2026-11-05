from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pharos import control_population_v014 as v014


def valid_page(source_ids: list[int], *, cell: v014.Cell = v014.CELLS[0]) -> pd.DataFrame:
    size = len(source_ids)
    nan = np.full(size, np.nan, dtype="float64")
    values: dict[str, object] = {
        "gaia_dr3_source_id": pd.Series(source_ids, dtype="int64"),
        "ra": pd.Series(np.full(size, 10.0), dtype="float64"),
        "dec": pd.Series(np.full(size, 20.0), dtype="float64"),
        "galactic_l": pd.Series(np.full(size, cell.longitude_min + 1.0), dtype="float64"),
        "galactic_b": pd.Series(
            np.full(size, 30.0 if cell.hemisphere == "north" else -30.0), dtype="float64"
        ),
        "parallax": pd.Series(np.full(size, 10.0), dtype="float64"),
        "parallax_error": pd.Series(np.full(size, 1.0), dtype="float64"),
        "parallax_over_error": pd.Series(np.full(size, 10.0), dtype="float64"),
        "pmra": pd.Series(nan.copy(), dtype="float64"),
        "pmdec": pd.Series(nan.copy(), dtype="float64"),
        "ruwe": pd.Series(np.full(size, 1.0), dtype="float64"),
        "astrometric_excess_noise": pd.Series(nan.copy(), dtype="float64"),
        "astrometric_excess_noise_sig": pd.Series(nan.copy(), dtype="float64"),
        "phot_g_mean_mag": pd.Series(np.full(size, 10.0), dtype="float64"),
        "phot_bp_rp_excess_factor": pd.Series(np.full(size, 1.0), dtype="float64"),
        "ipd_frac_multi_peak": pd.Series(nan.copy(), dtype="float64"),
        "ipd_frac_odd_win": pd.Series(nan.copy(), dtype="float64"),
        "duplicated_source": pd.Series(np.full(size, False), dtype="bool"),
        "non_single_star": pd.Series(np.zeros(size), dtype="int64"),
        "qso_probability": pd.Series(np.full(size, 0.0), dtype="float64"),
        "galaxy_probability": pd.Series(np.full(size, 0.0), dtype="float64"),
        "teff_gspphot": pd.Series(np.full(size, 5000.0), dtype="float64"),
        "logg_gspphot": pd.Series(nan.copy(), dtype="float64"),
        "distance_gspphot": pd.Series(nan.copy(), dtype="float64"),
        "ag_gspphot": pd.Series(nan.copy(), dtype="float64"),
        "wise_xm_angular_distance": pd.Series(np.full(size, 0.1), dtype="float64"),
        "wise_xm_n_neighbours": pd.Series(np.ones(size), dtype="int64"),
        "wise_xm_n_mates": pd.Series(np.zeros(size), dtype="int64"),
        "wise_xm_flag": pd.Series(np.ones(size), dtype="int64"),
        "allwise_designation": pd.Series(["WISE"] * size, dtype="object"),
        "w1mpro": pd.Series(np.full(size, 10.0), dtype="float64"),
        "w1mpro_error": pd.Series(np.full(size, 1.0857 / 5.0), dtype="float64"),
        "w1snr": pd.Series(np.full(size, 5.0), dtype="float64"),
        "w2mpro": pd.Series(np.full(size, 10.0), dtype="float64"),
        "w2mpro_error": pd.Series(np.full(size, 1.0857 / 5.0), dtype="float64"),
        "w2snr": pd.Series(np.full(size, 5.0), dtype="float64"),
        "w3mpro": pd.Series(np.full(size, 10.0), dtype="float64"),
        "w3mpro_error": pd.Series(np.full(size, 1.0857 / 3.0), dtype="float64"),
        "w3snr": pd.Series(np.full(size, 3.0), dtype="float64"),
        "w4mpro": pd.Series(nan.copy(), dtype="float64"),
        "w4mpro_error": pd.Series(nan.copy(), dtype="float64"),
        "w4snr": pd.Series(nan.copy(), dtype="float64"),
        "allwise_cc_flags": pd.Series([None] * size, dtype="object"),
        "allwise_ext_flg": pd.Series([None] * size, dtype="object"),
        "tmass_xm_angular_distance": pd.Series(np.full(size, 0.1), dtype="float64"),
        "tmass_designation": pd.Series(["2MASS"] * size, dtype="object"),
        "tmass_j_m": pd.Series(nan.copy(), dtype="float64"),
        "tmass_j_msigcom": pd.Series(nan.copy(), dtype="float64"),
        "tmass_h_m": pd.Series(nan.copy(), dtype="float64"),
        "tmass_h_msigcom": pd.Series(nan.copy(), dtype="float64"),
        "tmass_ks_m": pd.Series(np.full(size, 10.0), dtype="float64"),
        "tmass_ks_msigcom": pd.Series(np.full(size, 0.1), dtype="float64"),
    }
    return pd.DataFrame(values, columns=v014.GAIA_COLUMNS)


def test_registered_cells_quotas_and_round_robin_plan() -> None:
    assert len(v014.CELLS) == 24
    assert [cell.quota for cell in v014.CELLS] == [2292] * 16 + [2291] * 8
    assert sum(cell.quota for cell in v014.CELLS) == 55_000
    planner = v014.GaiaPlanner()
    plan = planner.next_request()
    assert plan is not None
    assert plan.logical_request_id == "gaia-0000"
    assert plan.cell.id == "l000-030-north"
    assert plan.requested_rows == 500
    assert plan.query_text.endswith("ORDER BY gs.source_id\n")
    assert "AND gs.b > 20.0" in plan.query_text


def test_query_templates_are_exactly_bounded() -> None:
    with pytest.raises(ValueError):
        v014.render_gaia_query(v014.CELLS[0], 0, 501)
    assert "0.008361111111111111" in v014.SIMBAD_QUERY
    assert "matched_ra" in v014.SIMBAD_QUERY
    assert v014.CHEN_DESCRIPTOR == (
        "Vizier:J/ApJS/211/25/catalog:columns=_RA,_DE,Name:row_limit=10000\n"
    )


def test_gaia_page_rejects_short_reordered_and_forged_snr() -> None:
    frame = valid_page([1])
    with pytest.raises(ValueError, match="short"):
        v014.normalize_gaia_page(frame, cell=v014.CELLS[0], cursor_before=0, requested_rows=2)
    reordered = frame.loc[:, list(reversed(v014.GAIA_COLUMNS))]
    with pytest.raises(ValueError, match="reordered"):
        v014.normalize_gaia_page(reordered, cell=v014.CELLS[0], cursor_before=0, requested_rows=1)
    frame.loc[0, "w1snr"] = 5.1
    with pytest.raises(ValueError, match="forged W1"):
        v014.normalize_gaia_page(frame, cell=v014.CELLS[0], cursor_before=0, requested_rows=1)


def test_optional_w4_registered_missingness_and_malformed_rejection() -> None:
    frame = valid_page([1])
    frame.loc[0, ["w4mpro", "w4mpro_error"]] = [8.0, 1.0857]
    normalized = v014.normalize_gaia_page(
        frame, cell=v014.CELLS[0], cursor_before=0, requested_rows=1
    )
    assert normalized.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]].isna().all()
    frame = valid_page([1])
    frame.loc[0, ["w4mpro", "w4mpro_error"]] = [8.0, -1.0]
    with pytest.raises(ValueError, match="nonpositive"):
        v014.normalize_gaia_page(frame, cell=v014.CELLS[0], cursor_before=0, requested_rows=1)


def test_spherical_boundary_and_local_simbad_recompute() -> None:
    exact_dec = 30.0 / 3600.0
    assert math.isclose(
        v014.pharos_spherical_sep_arcsec_v1(0.0, 0.0, 0.0, exact_dec),
        30.0,
        rel_tol=0,
        abs_tol=2e-14,
    )
    upload = pd.DataFrame(
        {
            "gaia_dr3_source_id": pd.Series([1], dtype="int64"),
            "ra": pd.Series([0.0], dtype="float64"),
            "dec": pd.Series([0.0], dtype="float64"),
        },
        columns=v014.SIMBAD_UPLOAD_COLUMNS,
    )
    raw = pd.DataFrame(
        [[1, "obj", "AGN", 0.0, 30.05 / 3600.0, 29.0]],
        columns=v014.SIMBAD_RAW_COLUMNS,
    ).astype(
        {
            "gaia_dr3_source_id": "int64",
            "matched_ra": "float64",
            "matched_dec": "float64",
            "server_angular_distance_arcsec": "float64",
        }
    )
    parent = valid_page([1])
    parent["ra"] = 0.0
    parent["dec"] = 0.0
    parent["gmag_bin_lower"] = 10.0
    parent["bp_rp_excess_bin_median"] = 1.0
    parent["bp_rp_excess_delta"] = 0.0
    normalized = v014.normalize_simbad_exclusions(raw, upload, parent)
    assert normalized.empty  # server value cannot override local >30 arcsec


def test_chen_exact_column_order_and_registered_matcher() -> None:
    parent = valid_page([1])
    parent["ra"] = 0.0
    parent["dec"] = 0.0
    parent["gmag_bin_lower"] = 10.0
    parent["bp_rp_excess_bin_median"] = 1.0
    parent["bp_rp_excess_delta"] = 0.0
    raw = pd.DataFrame(
        {
            "_RA": pd.Series([0.0, 0.0], dtype="float64"),
            "_DE": pd.Series([29.999 / 3600.0, 30.001 / 3600.0], dtype="float64"),
            "Name": pd.Series(["inside", "outside"], dtype="object"),
            "_raw_row_index": pd.Series([0, 1], dtype="int64"),
        },
        columns=v014.CHEN_RAW_COLUMNS,
    )
    matches = v014.match_chen_exclusions(raw, parent)
    assert list(matches["matched_object_id"]) == ["inside"]
    with pytest.raises(ValueError, match="reordered"):
        v014.validate_chen_raw(raw.loc[:, list(reversed(v014.CHEN_RAW_COLUMNS))])

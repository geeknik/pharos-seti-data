"""Unit tests for the IR-layer confounder vector.

Spot-checks each component's logic and confirms the scalar penalty is
the dot product of beta and the component vector.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pharos import confounders


def _empty_target_row() -> dict:
    """Minimal row that yields zero in every confounder component."""
    return {
        "gaia_dr3_source_id": 1,
        "wise_xm_angular_distance": 0.0,
        "wise_xm_n_neighbours": 1,
        "wise_xm_n_mates": 0,
        "galaxy_probability": 0.0,
        "qso_probability": 0.0,
        "galactic_b": 60.0,
        "phot_g_mean_mag": 10.0,
        "w3mpro": 14.0,
        "w4mpro": 12.0,
        "allwise_cc_flags": "0000",
        "allwise_ext_flg": 0,
        "allwise_nb": 1,
        "non_single_star": 0,
        "w1_w3_offset_arcsec_ra": 0.0,
        "w1_w3_offset_arcsec_dec": 0.0,
    }


class TestComponentBehavior:
    def test_clean_source_has_zero_penalty(self) -> None:
        df = pd.DataFrame([_empty_target_row()])
        result = confounders.compute_confounder_scores(df)
        assert float(result.penalty.iloc[0]) == pytest.approx(0.0)

    def test_wise_offset_fires_for_large_offset(self) -> None:
        row = _empty_target_row()
        row["w1_w3_offset_arcsec_ra"] = 5.59  # candidate G value
        row["w1_w3_offset_arcsec_dec"] = 0.64
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        mag = np.hypot(5.59, 0.64)
        expected_p = min(1.0, mag / confounders.WISE_OFFSET_SCALE_ARCSEC)
        assert result.vector["p_wise_offset"].iloc[0] == pytest.approx(expected_p)
        # With beta=5.0, this component alone should clear the
        # discard_confounded threshold (>= 4.0).
        assert float(result.penalty.iloc[0]) >= 4.0

    def test_wise_offset_zero_when_columns_missing(self) -> None:
        row = _empty_target_row()
        del row["w1_w3_offset_arcsec_ra"]
        del row["w1_w3_offset_arcsec_dec"]
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        assert float(result.vector["p_wise_offset"].iloc[0]) == 0.0

    def test_blend_fires_when_crowded_and_offset(self) -> None:
        row = _empty_target_row()
        row["wise_xm_angular_distance"] = 1.5
        row["wise_xm_n_neighbours"] = 3
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        # 1 - exp(-1.5 / 1.5) = 1 - exp(-1) ≈ 0.632
        assert result.vector["p_blend"].iloc[0] == pytest.approx(1.0 - np.exp(-1.0))

    def test_blend_zero_when_clean(self) -> None:
        df = pd.DataFrame([_empty_target_row()])
        result = confounders.compute_confounder_scores(df)
        assert result.vector["p_blend"].iloc[0] == pytest.approx(0.0)

    def test_low_galactic_lat_taper(self) -> None:
        cases = [
            (5.0, 1.0),  # well inside floor
            (10.0, 1.0),  # at floor
            (15.0, 0.5),  # halfway
            (20.0, 0.0),  # at taper end
            (45.0, 0.0),  # high latitude
        ]
        for b, expected in cases:
            row = _empty_target_row()
            row["galactic_b"] = b
            df = pd.DataFrame([row])
            result = confounders.compute_confounder_scores(df)
            assert result.vector["p_low_galactic_lat"].iloc[0] == pytest.approx(
                expected, abs=1e-9
            )

    def test_galaxy_and_qso_passthrough(self) -> None:
        row = _empty_target_row()
        row["galaxy_probability"] = 0.7
        row["qso_probability"] = 0.4
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        assert result.vector["p_galaxy"].iloc[0] == pytest.approx(0.7)
        assert result.vector["p_qso"].iloc[0] == pytest.approx(0.4)

    def test_bad_flag_triggers_on_cc_flags(self) -> None:
        row = _empty_target_row()
        row["allwise_cc_flags"] = "00D0"  # diffraction-spike contamination in W3
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        assert result.vector["p_bad_flag"].iloc[0] == 1.0

    def test_nss_indicator(self) -> None:
        row = _empty_target_row()
        row["non_single_star"] = 1
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        assert result.vector["p_nss"].iloc[0] == 1.0


class TestPenaltyDotProduct:
    def test_penalty_equals_beta_dot_p(self) -> None:
        row = _empty_target_row()
        row["w1_w3_offset_arcsec_ra"] = 3.21  # candidate B value
        row["galaxy_probability"] = 0.2
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)

        components = result.vector.drop(columns=["gaia_dr3_source_id"]).iloc[0]
        expected = sum(
            confounders.BETA_WEIGHTS[k] * components[f"p_{k}"]
            for k in confounders.BETA_WEIGHTS
        )
        assert float(result.penalty.iloc[0]) == pytest.approx(expected)

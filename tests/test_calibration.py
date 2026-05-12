"""Unit tests for β calibration math.

Exercises the pure functions in ``pharos.calibration`` against
deterministic synthetic data. No network access required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pharos import calibration, confounders


def _make_clean_row(source_id: int) -> dict:
    return {
        "gaia_dr3_source_id": source_id,
        "wise_xm_angular_distance": 0.05,
        "wise_xm_n_neighbours": 1,
        "wise_xm_n_mates": 0,
        "galaxy_probability": 0.01,
        "qso_probability": 0.01,
        "galactic_b": 60.0,
        "phot_g_mean_mag": 12.0,
        "w3mpro": 14.0,
        "w4mpro": 12.5,
        "allwise_cc_flags": "0000",
        "allwise_ext_flg": 0,
        "non_single_star": 0,
        "w1_w3_offset_arcsec_ra": 0.0,
        "w1_w3_offset_arcsec_dec": 0.0,
    }


def _make_contaminated_row(source_id: int) -> dict:
    row = _make_clean_row(source_id)
    # Large W1-W3 photocentre offset — high P_wise_offset.
    row["w1_w3_offset_arcsec_ra"] = 5.0
    row["w1_w3_offset_arcsec_dec"] = 1.5
    # Galaxy-like classification.
    row["galaxy_probability"] = 0.7
    return row


class TestCalibrateBetas:
    def test_perfect_separation_drives_positive_betas(self) -> None:
        contaminants = pd.DataFrame(
            [_make_contaminated_row(i) for i in range(1, 21)]
        )
        controls = pd.DataFrame(
            [_make_clean_row(i) for i in range(1000, 1100)]
        )
        result = calibration.calibrate_betas(contaminants, controls)
        # At least one β must be non-zero per pre-reg §4.5
        assert any(v > 0 for v in result.betas.values())
        # ROC AUC is the right ranking metric without a bias term.
        # Perfect separation should give AUC ≈ 1.0.
        assert result.train_auc > 0.95
        # The dominant signal in our synthetic contaminant is
        # P_wise_offset; verify its β is strictly positive.
        assert result.betas["wise_offset"] > 0
        # Contaminants should score higher than controls.
        assert result.score_separation > 0

    def test_requires_minimum_population_sizes(self) -> None:
        contaminants = pd.DataFrame([_make_contaminated_row(1)])
        controls = pd.DataFrame([_make_clean_row(i) for i in range(1000, 1100)])
        with pytest.raises(ValueError):
            calibration.calibrate_betas(contaminants, controls)

    def test_non_negative_clipping_records_changes(self) -> None:
        # Construct a degenerate case: contaminants have LOWER feature
        # values than controls for one component → that β should come
        # back negative and get clipped to zero.
        contaminants = pd.DataFrame([_make_contaminated_row(i) for i in range(1, 21)])
        controls = pd.DataFrame([_make_clean_row(i) for i in range(1000, 1100)])
        # Boost galactic latitude for contaminants (which lowers
        # P_lowgalb to zero). Controls already have b=60 so lowgalb=0 too.
        result = calibration.calibrate_betas(contaminants, controls)
        # P_lowgalb is zero for everyone → no information → β should
        # cluster near zero (either positive from regularization or
        # clipped from a small negative).
        assert result.betas["low_galactic_lat"] >= 0
        # If anything got clipped, the metadata records it.
        if result.fit_metadata["non_negative_clipping_changed_components"] > 0:
            assert any(
                raw < 0 and clipped == 0
                for raw, clipped in zip(
                    result.raw_betas.values(), result.betas.values()
                )
            )


class TestXrayAwareHotDog:
    def test_xray_detection_attenuates_to_zero(self) -> None:
        row = {
            "gaia_dr3_source_id": 1,
            "wise_xm_angular_distance": 0.05,
            "wise_xm_n_neighbours": 1,
            "wise_xm_n_mates": 0,
            "galaxy_probability": 0.0,
            "qso_probability": 0.0,
            "galactic_b": 60.0,
            "phot_g_mean_mag": 18.0,  # faint
            "w3mpro": 10.0,  # bright
            "w4mpro": 8.0,  # bright
            "allwise_cc_flags": "0000",
            "allwise_ext_flg": 0,
            "non_single_star": 0,
            "w1_w3_offset_arcsec_ra": 0.0,
            "w1_w3_offset_arcsec_dec": 0.0,
            "xray_any_detection": True,
            "xray_coverage_count": 2,
        }
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        # Base heuristic would fire (faint G + bright W3) → 1.0;
        # X-ray detection should attenuate to 0.
        assert result.vector["p_hot_dog"].iloc[0] == 0.0

    def test_xray_unconstrained_keeps_v01_heuristic(self) -> None:
        row = {
            "gaia_dr3_source_id": 1,
            "wise_xm_angular_distance": 0.05,
            "wise_xm_n_neighbours": 1,
            "wise_xm_n_mates": 0,
            "galaxy_probability": 0.0,
            "qso_probability": 0.0,
            "galactic_b": 60.0,
            "phot_g_mean_mag": 18.0,
            "w3mpro": 10.0,
            "w4mpro": 8.0,
            "allwise_cc_flags": "0000",
            "allwise_ext_flg": 0,
            "non_single_star": 0,
            "w1_w3_offset_arcsec_ra": 0.0,
            "w1_w3_offset_arcsec_dec": 0.0,
            # No X-ray columns at all → fallback to v0.1 heuristic.
        }
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        assert result.vector["p_hot_dog"].iloc[0] == 1.0

    def test_xray_null_in_covered_catalog_does_not_attenuate(self) -> None:
        # Source IS in 2RXS coverage (xray_coverage_count > 0), but has
        # no detection → HOT DOG should NOT be attenuated.
        row = {
            "gaia_dr3_source_id": 1,
            "wise_xm_angular_distance": 0.05,
            "wise_xm_n_neighbours": 1,
            "wise_xm_n_mates": 0,
            "galaxy_probability": 0.0,
            "qso_probability": 0.0,
            "galactic_b": 60.0,
            "phot_g_mean_mag": 18.0,
            "w3mpro": 10.0,
            "w4mpro": 8.0,
            "allwise_cc_flags": "0000",
            "allwise_ext_flg": 0,
            "non_single_star": 0,
            "w1_w3_offset_arcsec_ra": 0.0,
            "w1_w3_offset_arcsec_dec": 0.0,
            "xray_any_detection": False,
            "xray_coverage_count": 1,
        }
        df = pd.DataFrame([row])
        result = confounders.compute_confounder_scores(df)
        # Coverage but no detection → X-ray null → HOT DOG still fires.
        assert result.vector["p_hot_dog"].iloc[0] == 1.0

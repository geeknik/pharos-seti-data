"""Unit tests for empirical p-value and BH math.

These exercise the pure functions in ``pharos.calibrate`` and do not
require network access or a Gaia archive query.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pharos import calibrate


class TestLaplaceTailPValues:
    def test_max_score_returns_minimum_p(self) -> None:
        controls = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        targets = np.array([5.0])  # strictly larger than all controls
        p = calibrate.laplace_tail_p_values(targets, controls)
        # (1 + 0) / (1 + 5) = 1/6
        assert p[0] == pytest.approx(1.0 / 6.0)

    def test_min_score_returns_maximum_p(self) -> None:
        controls = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        targets = np.array([-1.0])
        p = calibrate.laplace_tail_p_values(targets, controls)
        # (1 + 5) / (1 + 5) = 1.0
        assert p[0] == pytest.approx(1.0)

    def test_tie_with_control_counts_as_ge(self) -> None:
        controls = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        targets = np.array([2.0])  # ties with one control
        p = calibrate.laplace_tail_p_values(targets, controls)
        # controls >= 2.0 are {2.0, 3.0, 4.0} -> count = 3
        # (1 + 3) / (1 + 5) = 4/6
        assert p[0] == pytest.approx(4.0 / 6.0)

    def test_nan_targets_propagate(self) -> None:
        controls = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        targets = np.array([np.nan, 1.5])
        p = calibrate.laplace_tail_p_values(targets, controls)
        assert np.isnan(p[0])
        assert np.isfinite(p[1])

    def test_nan_controls_dropped(self) -> None:
        controls_with_nan = np.array([0.0, np.nan, 2.0, np.nan, 4.0])
        targets = np.array([3.0])
        p_with_nan = calibrate.laplace_tail_p_values(targets, controls_with_nan)
        clean_controls = np.array([0.0, 2.0, 4.0])
        p_clean = calibrate.laplace_tail_p_values(targets, clean_controls)
        assert p_with_nan[0] == pytest.approx(p_clean[0])

    def test_empty_controls_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            calibrate.laplace_tail_p_values(np.array([1.0]), np.array([]))

    def test_p_value_bounds(self) -> None:
        rng = np.random.default_rng(42)
        controls = rng.normal(size=1000)
        targets = rng.normal(size=200)
        p = calibrate.laplace_tail_p_values(targets, controls)
        assert np.all(p > 0)
        assert np.all(p <= 1.0)


class TestToLogEvidence:
    def test_log_evidence_99th_percentile_is_two(self) -> None:
        # p = 0.01 -> -log10(0.01) = 2
        p = np.array([0.01])
        e = calibrate.to_log_evidence(p)
        assert e[0] == pytest.approx(2.0)

    def test_nan_propagates(self) -> None:
        p = np.array([np.nan, 0.1])
        e = calibrate.to_log_evidence(p)
        assert np.isnan(e[0])
        assert np.isfinite(e[1])

    def test_zero_or_negative_p_is_nan(self) -> None:
        p = np.array([0.0, -1.0, 0.5])
        e = calibrate.to_log_evidence(p)
        assert np.isnan(e[0])
        assert np.isnan(e[1])
        assert e[2] == pytest.approx(-np.log10(0.5))


class TestBenjaminiHochberg:
    def test_returns_nan_for_empty(self) -> None:
        q = calibrate.benjamini_hochberg(np.array([]))
        assert len(q) == 0

    def test_single_p_value(self) -> None:
        q = calibrate.benjamini_hochberg(np.array([0.04]))
        # n=1, q_(1) = 1 * 0.04 / 1 = 0.04
        assert q[0] == pytest.approx(0.04)

    def test_monotone_non_decreasing(self) -> None:
        rng = np.random.default_rng(0)
        p = rng.uniform(size=100)
        q = calibrate.benjamini_hochberg(p)
        order = np.argsort(p)
        sorted_q = q[order]
        assert np.all(np.diff(sorted_q) >= -1e-12)

    def test_q_capped_at_one(self) -> None:
        p = np.array([0.5, 0.9, 0.99])
        q = calibrate.benjamini_hochberg(p)
        assert np.all(q <= 1.0)

    def test_known_example(self) -> None:
        # Classic worked example: BH q-values for these p's should match
        # the standard step-up procedure.
        p = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.10, 0.50])
        q = calibrate.benjamini_hochberg(p)
        # q_(7) = 7 * 0.50 / 7 = 0.50
        # q_(6) = min(q_(7), 7 * 0.10 / 6) = min(0.50, 0.1167) = 0.1167
        # q_(5) = min(0.1167, 7 * 0.05 / 5) = min(0.1167, 0.07) = 0.07
        # q_(4) = min(0.07, 7 * 0.04 / 4) = min(0.07, 0.07) = 0.07
        # q_(3) = min(0.07, 7 * 0.03 / 3) = 0.07
        # q_(2) = min(0.07, 7 * 0.02 / 2) = 0.07
        # q_(1) = min(0.07, 7 * 0.01 / 1) = 0.07
        expected = np.array([0.07, 0.07, 0.07, 0.07, 0.07, 7 * 0.10 / 6, 0.50])
        assert q == pytest.approx(expected, abs=1e-10)

    def test_nan_propagates(self) -> None:
        p = np.array([0.01, np.nan, 0.05])
        q = calibrate.benjamini_hochberg(p)
        assert np.isnan(q[1])
        assert np.isfinite(q[0]) and np.isfinite(q[2])


class TestCalibratedScores:
    def test_pipeline_with_pandas_series(self) -> None:
        rng = np.random.default_rng(7)
        controls = pd.Series(rng.normal(size=500), index=range(1000, 1500))
        targets = pd.Series(rng.normal(size=10), index=range(2000, 2010))
        out = calibrate.calibrate_ir_evidence(targets, controls)
        assert set(out.table.columns) == {"ir_evidence", "ir_empirical_p_value"}
        assert list(out.table.index) == list(targets.index)

    def test_requires_pandas_series(self) -> None:
        with pytest.raises(TypeError):
            calibrate.calibrate_ir_evidence(np.array([1.0]), np.array([0.0, 1.0]))


class TestComputeLeadScores:
    def test_no_data_quality_penalty_defaults_to_zero(self) -> None:
        e = pd.Series([2.0, 3.0], index=[1, 2])
        q = pd.Series([1.0, 1.0], index=[1, 2])
        p = pd.Series([0.5, 1.5], index=[1, 2])
        lead = calibrate.compute_lead_scores(e, q, p)
        assert lead.loc[1] == pytest.approx(1.0 * 2.0 - 0.5 - 0.0)
        assert lead.loc[2] == pytest.approx(1.0 * 3.0 - 1.5 - 0.0)

    def test_coverage_quality_attenuates_evidence(self) -> None:
        e = pd.Series([4.0], index=[1])
        q_full = pd.Series([1.0], index=[1])
        q_half = pd.Series([0.5], index=[1])
        p = pd.Series([0.0], index=[1])
        full = calibrate.compute_lead_scores(e, q_full, p)
        half = calibrate.compute_lead_scores(e, q_half, p)
        assert full.loc[1] == pytest.approx(4.0)
        assert half.loc[1] == pytest.approx(2.0)

"""Empirical p-value calibration and BH FDR control for Pharos.

Implements the Laplace-smoothed rank estimator from manuscript §5.1 and
the lead-level empirical p-value plus Benjamini-Hochberg q-value from
manuscript §5.5. Both operate within a single coverage class — the
caller is responsible for stratifying by class before calling these
functions (pre_registration/v0.1_ir_benchmark.md §6, §8).

All inputs and outputs are pure data structures. No I/O, no global
state. Functions are deterministic given inputs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def laplace_tail_p_values(
    target_scores: np.ndarray,
    control_scores: np.ndarray,
) -> np.ndarray:
    """Laplace-smoothed empirical tail probability.

    For each target score s_i, returns

        p_i = (1 + #{c in C : s_c >= s_i}) / (1 + |C|)

    Source: manuscript §5.1 and §5.5. NaN target scores propagate as NaN
    p-values. Control NaNs are dropped before counting.
    """
    target = np.asarray(target_scores, dtype=float)
    controls = np.asarray(control_scores, dtype=float)
    controls = controls[np.isfinite(controls)]
    n_controls = len(controls)

    if n_controls == 0:
        raise ValueError("control population is empty")

    controls_sorted = np.sort(controls)
    out = np.full(target.shape, np.nan, dtype=float)
    finite_mask = np.isfinite(target)
    if not np.any(finite_mask):
        return out

    # searchsorted on the sorted controls. count of controls >= s is
    # n_controls - searchsorted(controls_sorted, s, side='left').
    insert_positions = np.searchsorted(
        controls_sorted, target[finite_mask], side="left"
    )
    counts_ge = n_controls - insert_positions
    out[finite_mask] = (1.0 + counts_ge) / (1.0 + n_controls)
    return out


def to_log_evidence(p_values: np.ndarray) -> np.ndarray:
    """Convert empirical p-values to log-evidence E_i = -log10(p_i).

    Manuscript §5.1. p=0 is impossible by construction (Laplace smoothing)
    so the result is always finite where the input is finite.
    """
    p = np.asarray(p_values, dtype=float)
    out = np.full(p.shape, np.nan, dtype=float)
    finite = np.isfinite(p) & (p > 0)
    out[finite] = -np.log10(p[finite])
    return out


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg q-values for an array of p-values.

    Standard step-up procedure: q_(i) = min over k >= i of (n * p_(k) / k),
    with q_i constrained to be monotone non-decreasing in p_i. NaN
    p-values propagate as NaN q-values.
    """
    p = np.asarray(p_values, dtype=float)
    out = np.full(p.shape, np.nan, dtype=float)
    finite_mask = np.isfinite(p)
    p_finite = p[finite_mask]
    n = len(p_finite)
    if n == 0:
        return out

    order = np.argsort(p_finite)
    p_sorted = p_finite[order]
    ranks = np.arange(1, n + 1, dtype=float)
    q_sorted = p_sorted * n / ranks

    # Enforce monotone non-decreasing q as p increases:
    # walk from largest p downward, taking min of running and current q.
    q_monotone = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q_monotone = np.minimum(q_monotone, 1.0)

    q_finite = np.empty_like(q_monotone)
    q_finite[order] = q_monotone
    out[finite_mask] = q_finite
    return out


@dataclass(frozen=True)
class CalibratedScores:
    """One row per source, indexed by gaia_dr3_source_id."""

    table: pd.DataFrame  # columns: ir_evidence, ir_empirical_p_value


def calibrate_ir_evidence(
    target_ir_raw: pd.Series,
    control_ir_raw: pd.Series,
) -> CalibratedScores:
    """Convert raw IR residual scores into calibrated E_IR and empirical p.

    Both inputs are gaia_dr3_source_id-indexed Series of raw scores
    (e.g., ``composite_ir_evidence_raw`` output from ``pharos.ir_sed``).
    The control series must come from a coverage-matched control
    population for the result to be meaningful.
    """
    if not isinstance(target_ir_raw, pd.Series):
        raise TypeError("target_ir_raw must be a pandas Series")
    if not isinstance(control_ir_raw, pd.Series):
        raise TypeError("control_ir_raw must be a pandas Series")

    p_values = laplace_tail_p_values(
        target_ir_raw.to_numpy(dtype=float),
        control_ir_raw.to_numpy(dtype=float),
    )
    e_values = to_log_evidence(p_values)
    table = pd.DataFrame(
        {
            "ir_evidence": e_values,
            "ir_empirical_p_value": p_values,
        },
        index=target_ir_raw.index,
    )
    table.index.name = "gaia_dr3_source_id"
    logger.info(
        "calibrated IR evidence: n_targets=%d, median E=%.3f, max E=%.3f",
        len(table),
        float(np.nanmedian(e_values)) if np.any(np.isfinite(e_values)) else math.nan,
        float(np.nanmax(e_values)) if np.any(np.isfinite(e_values)) else math.nan,
    )
    return CalibratedScores(table=table)


# ---------------------------------------------------------------------------
# Lead-level p-values and BH (manuscript §5.5).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeadScores:
    """Final per-source lead score, empirical lead p, and BH q-value."""

    table: pd.DataFrame  # columns: lead_score, lead_empirical_p, fdr_q_value


def compute_lead_scores(
    ir_evidence: pd.Series,
    coverage_confidence: pd.Series,
    confounder_penalty: pd.Series,
    data_quality_penalty: pd.Series | None = None,
) -> pd.Series:
    """Compose the v0.1 LeadScore per pre_registration §8.

    For v0.1 there is exactly one modality (IR), no independence-weighted
    cross-modal bonus, no geometry prior, and no repeatability term:

        LeadScore = q_IR * E_IR - beta . P_IR - D
    """
    aligned = pd.concat(
        [
            ir_evidence.rename("e"),
            coverage_confidence.rename("q"),
            confounder_penalty.rename("p"),
            (data_quality_penalty.rename("d") if data_quality_penalty is not None else None),
        ],
        axis=1,
    )
    if "d" not in aligned.columns:
        aligned["d"] = 0.0
    aligned = aligned.fillna({"q": 0.0, "p": 0.0, "d": 0.0})
    lead = aligned["q"] * aligned["e"] - aligned["p"] - aligned["d"]
    lead.name = "lead_score"
    return lead


def calibrate_lead_scores(
    target_lead: pd.Series,
    control_lead: pd.Series,
) -> LeadScores:
    """Compute lead empirical p-values and BH q-values within a coverage class.

    Manuscript §5.5. Both series must come from the same coverage class.
    The control lead-score distribution is the empirical null for that
    class; the q-values are not interpretable across coverage classes.
    """
    p_values = laplace_tail_p_values(
        target_lead.to_numpy(dtype=float),
        control_lead.to_numpy(dtype=float),
    )
    q_values = benjamini_hochberg(p_values)
    table = pd.DataFrame(
        {
            "lead_score": target_lead,
            "lead_empirical_p_value_within_coverage_class": p_values,
            "fdr_q_value_within_coverage_class": q_values,
        },
        index=target_lead.index,
    )
    return LeadScores(table=table)

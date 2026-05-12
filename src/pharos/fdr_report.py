"""Empirical FDR calibration report for Pharos v0.1.

The pre-registered v0.1 ranked list lives within the WISE-only coverage
class. To verify the Benjamini-Hochberg procedure delivers the intended
FDR bound, we run it against a held-out null sample drawn from the same
quiet-negative control population that fits the locus.

Procedure:
  1. Split the quiet-negative controls 50/50 (deterministic).
  2. Fit the locus on the first half.
  3. Score the second half against that locus, compute confounder
     penalties, LeadScores.
  4. Use a separate, disjoint control split to provide the empirical
     LeadScore null distribution.
  5. Apply BH FDR within the single coverage class. Count rejections
     at q ∈ {0.01, 0.05, 0.10}.

For a pure null sample, BH should give *fewer* rejections than the
nominal q × N bound — the procedure is conservative under the null.
Any large excess of rejections indicates miscalibration.

No I/O in this module; ``pharos.cli.cmd_run_fdr_report`` writes the
results to ``controls/fdr_report/``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pharos import calibrate, confounders, ir_sed

logger = logging.getLogger(__name__)

DEFAULT_Q_THRESHOLDS: tuple[float, ...] = (0.01, 0.05, 0.10)


@dataclass(frozen=True)
class FDRReportResult:
    """Per-target FDR rows plus a per-q summary table."""

    rows: pd.DataFrame  # one row per target (the second half of the split)
    summary: pd.DataFrame  # one row per q threshold
    locus_size: int
    target_size: int
    null_size: int


def _three_way_split(
    controls: pd.DataFrame, random_state: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stratified split: 50% locus, 25% target, 25% LeadScore null."""
    rng = np.random.default_rng(random_state)
    teff_bin = pd.cut(
        controls["teff_gspphot"],
        bins=list(ir_sed.TEFF_BIN_EDGES_K),
        labels=False,
    )
    locus_idx: list[int] = []
    target_idx: list[int] = []
    null_idx: list[int] = []
    for _, group in controls.groupby(teff_bin, dropna=False):
        idx = group.index.to_numpy().copy()
        rng.shuffle(idx)
        n = len(idx)
        n_locus = n // 2
        n_target = (n - n_locus) // 2
        locus_idx.extend(idx[:n_locus].tolist())
        target_idx.extend(idx[n_locus : n_locus + n_target].tolist())
        null_idx.extend(idx[n_locus + n_target :].tolist())
    return (
        controls.loc[locus_idx].copy(),
        controls.loc[target_idx].copy(),
        controls.loc[null_idx].copy(),
    )


def run_fdr_report(
    controls: pd.DataFrame,
    *,
    q_thresholds: tuple[float, ...] = DEFAULT_Q_THRESHOLDS,
    random_state: int = 0,
) -> FDRReportResult:
    """Run the BH FDR calibration on a null sample drawn from controls."""
    if "w3_ks" not in controls.columns:
        raise ValueError(
            "controls missing 'w3_ks' — call ir_sed.add_color_indices first"
        )

    locus_df, target_df, null_df = _three_way_split(
        controls, random_state=random_state
    )
    logger.info(
        "fdr report: locus=%d, target=%d, null=%d sources",
        len(locus_df),
        len(target_df),
        len(null_df),
    )

    locus = ir_sed.fit_control_locus(locus_df)

    def _calibrated_lead(df: pd.DataFrame, control_raw: pd.Series) -> pd.Series:
        scores = ir_sed.score_ir_residuals(df, locus).scores
        raw = ir_sed.composite_ir_evidence_raw(scores)
        raw_indexed = pd.Series(
            raw.to_numpy(),
            index=scores["gaia_dr3_source_id"].astype("int64").to_numpy(),
        )
        ir_cal = calibrate.calibrate_ir_evidence(raw_indexed, control_raw)
        conf = confounders.compute_confounder_scores(df)
        coverage = pd.Series(1.0, index=ir_cal.table.index)
        lead = calibrate.compute_lead_scores(
            ir_cal.table["ir_evidence"], coverage, conf.penalty
        )
        return lead, ir_cal.table["ir_evidence"], conf.penalty

    # The locus_df serves as the IR-evidence reference distribution. We
    # score the locus_df against its own locus to produce control_raw,
    # which calibrate_ir_evidence uses for empirical p-values.
    locus_scores = ir_sed.score_ir_residuals(locus_df, locus).scores
    control_raw = ir_sed.composite_ir_evidence_raw(locus_scores)
    control_raw_indexed = pd.Series(
        control_raw.to_numpy(),
        index=locus_scores["gaia_dr3_source_id"].astype("int64").to_numpy(),
    )

    null_lead, _, _ = _calibrated_lead(null_df, control_raw_indexed)
    target_lead, target_ir, target_penalty = _calibrated_lead(
        target_df, control_raw_indexed
    )

    lead_cal = calibrate.calibrate_lead_scores(target_lead, null_lead)
    rows = lead_cal.table.copy()
    rows["ir_evidence"] = target_ir.reindex(rows.index).to_numpy()
    rows["confounder_penalty"] = target_penalty.reindex(rows.index).to_numpy()
    rows.index.name = "gaia_dr3_source_id"

    n_total = len(rows)
    summary_rows: list[dict] = []
    for q in q_thresholds:
        rejections = (
            rows["fdr_q_value_within_coverage_class"] <= q
        ).sum()
        rate = rejections / n_total if n_total > 0 else 0.0
        summary_rows.append(
            {
                "q_threshold": q,
                "n_total": n_total,
                "n_rejections": int(rejections),
                "rejection_rate": rate,
                "nominal_bound": q,
            }
        )
    summary = pd.DataFrame(summary_rows)
    logger.info(
        "FDR rejection counts on null sample:\n%s", summary.to_string(index=False)
    )
    return FDRReportResult(
        rows=rows.reset_index(),
        summary=summary,
        locus_size=len(locus_df),
        target_size=len(target_df),
        null_size=len(null_df),
    )

"""Synthetic-injection recovery for Pharos v0.1.

Pre-registration §7 (secondary criterion) requires that a synthetic-injection
set of ≥100 controlled W3-excess sources is recovered at the expected
per-σ rate. This module implements that injection-and-recovery pipeline:

  1. Split the quiet-negative control population 50/50 (deterministic
     random_state=0). The first half fits the stellar locus; the second
     half is the source pool into which excesses are injected.
  2. For each source in the injection pool, inject controlled W3-Ks
     excesses at multiple σ levels (default: 5σ, 10σ, 20σ).
  3. Score the injected sources against the locus fitted on the first
     half.
  4. Report recovery rate per σ: fraction of injections whose
     calibrated IR evidence clears a pre-registered threshold.

Recovery threshold for v0.1 is the ``needs_human_review`` evidence
floor: ``ir_evidence >= 2.0`` (a 99th-percentile-or-better empirical
tail probability against the matched control bin). Pre-reg §8.

No I/O in this module — the caller is responsible for loading the
quiet-negative controls and writing the result table. See
``pharos.cli.cmd_run_injection_recovery`` for the CLI binding.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pharos import calibrate, ir_sed

logger = logging.getLogger(__name__)

# Default σ levels per pre-reg §7.
DEFAULT_INJECTION_SIGMAS: tuple[float, ...] = (5.0, 10.0, 20.0)

# Default recovery threshold: needs_human_review evidence floor.
DEFAULT_RECOVERY_THRESHOLD: float = 2.0


@dataclass(frozen=True)
class InjectionRecoveryResult:
    """Per-injection rows plus a per-σ summary."""

    rows: pd.DataFrame  # one row per (source, σ)
    summary: pd.DataFrame  # one row per σ
    locus_size: int
    injection_pool_size: int


def _split_controls_5050(
    controls: pd.DataFrame, random_state: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic 50/50 split. Sources are stratified by Teff bin to
    keep the locus and the injection pool comparable across stellar
    types — without this, the smaller pool can miss bins entirely."""
    if "teff_gspphot" not in controls.columns:
        raise ValueError("controls missing 'teff_gspphot' for stratified split")
    rng = np.random.default_rng(random_state)
    teff_bin = pd.cut(
        controls["teff_gspphot"], bins=list(ir_sed.TEFF_BIN_EDGES_K), labels=False
    )
    locus_idx: list[int] = []
    pool_idx: list[int] = []
    for _, group in controls.groupby(teff_bin, dropna=False):
        idx = group.index.to_numpy().copy()
        rng.shuffle(idx)
        half = len(idx) // 2
        locus_idx.extend(idx[:half].tolist())
        pool_idx.extend(idx[half:].tolist())
    return controls.loc[locus_idx].copy(), controls.loc[pool_idx].copy()


def _inject_w3_excess_into_row(
    source_row: pd.Series, sigma: float, w3_ks_iqr: float
) -> dict:
    """Return a dict of the source's measurable fields with W3 brightened
    by ``sigma`` Gaussian-equivalent standard deviations of the local
    W3-Ks locus IQR.

    A positive σ produces a NEGATIVE shift in mag (brighter source),
    which raises the W3-Ks color above the locus — exactly the regime a
    real IR-excess source would occupy.
    """
    gaussian_sigma = w3_ks_iqr / 1.349  # IQR -> equivalent Gaussian σ
    mag_shift = -sigma * gaussian_sigma
    out = source_row.to_dict()
    out["w3mpro"] = float(out["w3mpro"]) + mag_shift
    # Re-derive w3_ks: it's added later by add_color_indices.
    return out


def _gaussian_sigma_for_bin(locus: ir_sed.ControlLocus, bin_key: tuple) -> float:
    iqr, _ = ir_sed._locus_value_with_fallback(locus, bin_key, "w3_ks_iqr")
    return iqr if math.isfinite(iqr) and iqr > 0 else float("nan")


def run_injection_recovery(
    controls: pd.DataFrame,
    *,
    sigmas: tuple[float, ...] = DEFAULT_INJECTION_SIGMAS,
    threshold: float = DEFAULT_RECOVERY_THRESHOLD,
    max_pool_size: int | None = 200,
    random_state: int = 0,
) -> InjectionRecoveryResult:
    """Run the v0.1 synthetic injection-recovery pipeline.

    Args:
        controls: quiet-negative control sources (post-fetch). Must have
            stratification bins and color indices computed already.
        sigmas: σ levels at which to inject W3 excesses.
        threshold: ir_evidence ≥ threshold counts as "recovered".
        max_pool_size: cap the injection pool. Default 200 caps total
            injections at 200 × |sigmas| (600 for the default 3-σ set).
        random_state: deterministic split.
    """
    if "w3_ks" not in controls.columns:
        raise ValueError(
            "controls missing 'w3_ks' column — call ir_sed.add_color_indices first"
        )

    locus_half, pool_half = _split_controls_5050(controls, random_state=random_state)
    if max_pool_size is not None and len(pool_half) > max_pool_size:
        pool_half = pool_half.sample(
            n=max_pool_size, random_state=random_state
        ).copy()

    locus = ir_sed.fit_control_locus(locus_half)
    logger.info(
        "injection: locus fit on %d sources; pool size %d; sigmas %s",
        len(locus_half),
        len(pool_half),
        sigmas,
    )

    # Pre-compute per-pool-row IQR (constant across injections at the
    # same source). Sources whose IQR is NaN at all bin levels are
    # excluded — the injection wouldn't be calibratable.
    bin_cols = ir_sed._BIN_COLS
    pool_iqr: list[float] = []
    for _, src in pool_half.iterrows():
        bin_key = tuple(src[c] for c in bin_cols)
        pool_iqr.append(_gaussian_sigma_for_bin(locus, bin_key))
    pool_half = pool_half.copy()
    pool_half["_w3_ks_iqr_at_source"] = pool_iqr
    valid_pool = pool_half.dropna(subset=["_w3_ks_iqr_at_source"]).copy()
    if len(valid_pool) < len(pool_half):
        logger.warning(
            "dropped %d pool sources with no defined locus IQR",
            len(pool_half) - len(valid_pool),
        )

    # Compute the control-side raw IR evidence distribution once, for
    # the empirical-p-value calibration. This is the same locus_half
    # population scored against its own locus.
    locus_with_bins = locus_half.copy()
    locus_scores = ir_sed.score_ir_residuals(locus_with_bins, locus)
    control_raw = ir_sed.composite_ir_evidence_raw(locus_scores.scores)
    control_raw_indexed = pd.Series(
        control_raw.to_numpy(),
        index=locus_scores.scores["gaia_dr3_source_id"].astype("int64").to_numpy(),
    )

    # Build the injection batch: for each pool source × sigma, produce
    # a perturbed copy. We pass them all through the pipeline at once.
    rows: list[dict] = []
    for sigma in sigmas:
        for _, src in valid_pool.iterrows():
            iqr = float(src["_w3_ks_iqr_at_source"])
            injected = _inject_w3_excess_into_row(src, sigma, iqr)
            rows.append(
                {
                    "gaia_dr3_source_id": int(src["gaia_dr3_source_id"]),
                    "sigma": sigma,
                    "w3_ks_iqr_at_source": iqr,
                    "w3mpro_original": float(src["w3mpro"]),
                    "w3mpro_injected": injected["w3mpro"],
                    "tmass_ks_m": float(src["tmass_ks_m"]),
                }
            )

    injection_df = pd.DataFrame(rows)
    # Score the injected rows. We need w3mpro replaced with the injected
    # value, w4 left alone, and we recompute w3_ks. Sign convention
    # matches ir_sed.add_color_indices: w3_ks = Ks − W3 (positive z = excess).
    injection_df["w3_ks"] = injection_df["tmass_ks_m"] - injection_df["w3mpro_injected"]
    injection_df["w4_ks"] = float("nan")  # injection is W3-only by pre-reg §7

    # Bring over bin labels from the original pool source.
    pool_bins = valid_pool.set_index("gaia_dr3_source_id")[list(bin_cols)]
    injection_df = injection_df.join(pool_bins, on="gaia_dr3_source_id")

    # score_ir_residuals expects unique gaia_dr3_source_id per row — but
    # we have duplicates (one row per σ per source). Score in σ-grouped
    # batches and re-attach.
    scored_rows: list[pd.DataFrame] = []
    for sigma, group in injection_df.groupby("sigma"):
        scores = ir_sed.score_ir_residuals(group, locus).scores
        target_raw = ir_sed.composite_ir_evidence_raw(scores)
        target_raw_indexed = pd.Series(
            target_raw.to_numpy(),
            index=scores["gaia_dr3_source_id"].astype("int64").to_numpy(),
            name="raw",
        )
        ir_cal = calibrate.calibrate_ir_evidence(target_raw_indexed, control_raw_indexed)
        merged = group.assign(
            ir_evidence=ir_cal.table["ir_evidence"].reindex(
                group["gaia_dr3_source_id"].astype("int64").to_numpy()
            ).to_numpy(),
            ir_empirical_p_value=ir_cal.table["ir_empirical_p_value"].reindex(
                group["gaia_dr3_source_id"].astype("int64").to_numpy()
            ).to_numpy(),
        )
        scored_rows.append(merged)

    full = pd.concat(scored_rows, ignore_index=True)
    full["recovered"] = full["ir_evidence"] >= threshold

    summary_rows: list[dict] = []
    for sigma, g in full.groupby("sigma"):
        recovered_count = int(g["recovered"].sum())
        total = len(g)
        rate = recovered_count / total if total > 0 else float("nan")
        summary_rows.append(
            {
                "sigma": float(sigma),
                "n_injections": total,
                "n_recovered": recovered_count,
                "recovery_rate": rate,
                "median_ir_evidence": float(g["ir_evidence"].median()),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("sigma").reset_index(drop=True)
    logger.info("injection recovery summary:\n%s", summary.to_string(index=False))
    return InjectionRecoveryResult(
        rows=full,
        summary=summary,
        locus_size=len(locus_half),
        injection_pool_size=len(valid_pool),
    )

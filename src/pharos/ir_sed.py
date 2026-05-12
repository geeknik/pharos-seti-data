"""IR residual scoring for Pharos v0.1.

This module implements the data-driven stellar locus residual model used by
the IR layer. Rather than predicting absolute W3/W4 magnitudes from a
synthetic stellar SED grid, we compute color indices relative to the
2MASS Ks anchor and compare each source to the median locus of the
quiet-negative control population in a matched stratification bin.

The result is a per-source raw residual z-score for W3 and W4 separately,
suitable as input to the empirical-p-value calibration in
``pharos.calibrate``. Robust statistics (median + IQR) are used so a
single contaminated control bin cannot pull the locus.

Stratification bins must match the pre-registered bins in
``pre_registration/v0.1_ir_benchmark.md`` §4. Adjusting them requires a
versioned superseding pre-registration document.

The pre-reg currently specifies a BT-Settl synthetic SED grid. v0.1 uses
the data-driven stellar-locus approach below instead, which is simpler,
has no external grid dependency, and is empirically defensible because
the quiet-negative control population is itself defined as clean
main-sequence sources. The pre-reg will need a minor amendment (or
v0.1.1) to reflect this choice before freeze.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-registered stratification bins.
# Source: pre_registration/v0.1_ir_benchmark.md §4.
# ---------------------------------------------------------------------------
TEFF_BIN_EDGES_K: tuple[float, ...] = (0.0, 4000.0, 5500.0, 7000.0, math.inf)
GMAG_BIN_WIDTH: float = 0.5
DISTANCE_BIN_WIDTH_PC: float = 25.0
GALACTIC_LAT_BIN_EDGES_DEG: tuple[float, ...] = (0.0, 10.0, 30.0, math.inf)

# Minimum number of controls in a bin to trust its median + IQR. Below this,
# the source falls back to the parent (coarser) bin. Pre-registered.
MIN_CONTROL_BIN_SIZE: int = 30

# ---------------------------------------------------------------------------
# Required columns from the source dataframe. Each is produced by the
# Gaia + AllWISE + 2MASS join in ``pharos.sources``.
# ---------------------------------------------------------------------------
_REQUIRED_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "phot_g_mean_mag",
    "parallax",
    "galactic_b",
    "teff_gspphot",
    "tmass_ks_m",
    "tmass_ks_msigcom",
    "w3mpro",
    "w3mpro_error",
    "w4mpro",
    "w4mpro_error",
)


@dataclass(frozen=True)
class ControlLocus:
    """Median and IQR of color indices in each stratification bin."""

    medians: pd.DataFrame  # indexed by bin key, columns: w3_ks_median, w4_ks_median
    iqrs: pd.DataFrame  # indexed by bin key, columns: w3_ks_iqr, w4_ks_iqr
    counts: pd.Series  # indexed by bin key, value: n controls in bin


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"input dataframe missing required columns: {missing}")


def add_color_indices(df: pd.DataFrame) -> pd.DataFrame:
    """Add the Ks–W3 and Ks–W4 anomaly indices and their propagated errors.

    These are stored under the legacy column names ``w3_ks`` and
    ``w4_ks`` for compatibility with downstream code, but the *signed
    convention* is (Ks magnitude) − (WISE magnitude). An IR excess
    brightens W3/W4 (smaller magnitude) which raises this index, giving
    a positive residual z-score against the locus — the natural sign
    for an upper-tail empirical-p-value test.

    ``w4_ks`` is left as NaN where W4 is not detected (the W4 channel is
    optional in v0.1 — pre-reg §2 requires only W3 SNR >= 3).
    """
    _validate_columns(df)
    out = df.copy()
    out["w3_ks"] = out["tmass_ks_m"] - out["w3mpro"]
    out["w3_ks_err"] = np.sqrt(out["w3mpro_error"] ** 2 + out["tmass_ks_msigcom"] ** 2)
    out["w4_ks"] = out["tmass_ks_m"] - out["w4mpro"]
    out["w4_ks_err"] = np.sqrt(out["w4mpro_error"] ** 2 + out["tmass_ks_msigcom"] ** 2)
    return out


def add_stratification_bins(df: pd.DataFrame) -> pd.DataFrame:
    """Add the bin labels used for matched-control residual scoring.

    Bins are defined by pre-registered cuts. Sources falling outside any
    bin (e.g., missing Teff) get ``NaN`` labels and are excluded from the
    locus-fit but still get residuals if they fall into a coarser bin
    during scoring fallback.
    """
    _validate_columns(df)
    out = df.copy()

    out["teff_bin"] = pd.cut(
        out["teff_gspphot"], bins=list(TEFF_BIN_EDGES_K), labels=False, right=False
    )

    g_min = math.floor(out["phot_g_mean_mag"].min() / GMAG_BIN_WIDTH) * GMAG_BIN_WIDTH
    g_max = math.ceil(out["phot_g_mean_mag"].max() / GMAG_BIN_WIDTH) * GMAG_BIN_WIDTH
    if not math.isfinite(g_min) or not math.isfinite(g_max) or g_min == g_max:
        out["gmag_bin"] = np.nan
    else:
        gmag_edges = np.arange(g_min, g_max + GMAG_BIN_WIDTH, GMAG_BIN_WIDTH)
        out["gmag_bin"] = pd.cut(
            out["phot_g_mean_mag"], bins=gmag_edges, labels=False, right=False
        )

    distance_pc = 1000.0 / out["parallax"].where(out["parallax"] > 0)
    out["distance_pc"] = distance_pc
    d_max = math.ceil(distance_pc.max() / DISTANCE_BIN_WIDTH_PC) * DISTANCE_BIN_WIDTH_PC
    if not math.isfinite(d_max) or d_max <= 0:
        out["distance_bin"] = np.nan
    else:
        distance_edges = np.arange(0.0, d_max + DISTANCE_BIN_WIDTH_PC, DISTANCE_BIN_WIDTH_PC)
        out["distance_bin"] = pd.cut(distance_pc, bins=distance_edges, labels=False, right=False)

    abs_b = out["galactic_b"].abs()
    out["abs_galactic_b"] = abs_b
    out["lat_bin"] = pd.cut(
        abs_b, bins=list(GALACTIC_LAT_BIN_EDGES_DEG), labels=False, right=False
    )
    return out


_BIN_COLS: tuple[str, ...] = ("teff_bin", "gmag_bin", "distance_bin", "lat_bin")


def _robust_iqr(x: pd.Series) -> float:
    valid = x.dropna()
    if len(valid) < 2:
        return float("nan")
    q75, q25 = np.percentile(valid, [75, 25])
    iqr = q75 - q25
    return float(iqr) if iqr > 0 else float("nan")


def fit_control_locus(controls: pd.DataFrame) -> ControlLocus:
    """Compute the per-bin median W3-Ks and W4-Ks color of the controls.

    The control dataframe must already have color indices and bin labels
    (``add_color_indices`` then ``add_stratification_bins``).
    """
    for col in (*_BIN_COLS, "w3_ks", "w4_ks"):
        if col not in controls.columns:
            raise ValueError(f"controls missing column {col!r}")

    grouped = controls.groupby(list(_BIN_COLS), dropna=False)
    medians = grouped[["w3_ks", "w4_ks"]].median().rename(
        columns={"w3_ks": "w3_ks_median", "w4_ks": "w4_ks_median"}
    )
    iqrs = grouped[["w3_ks", "w4_ks"]].agg(_robust_iqr).rename(
        columns={"w3_ks": "w3_ks_iqr", "w4_ks": "w4_ks_iqr"}
    )
    counts = grouped.size().rename("n_controls")
    logger.info(
        "fit control locus: %d non-empty bins, total controls = %d",
        len(counts),
        int(counts.sum()),
    )
    return ControlLocus(medians=medians, iqrs=iqrs, counts=counts)


# IQR of a unit Gaussian = 2 * 0.6745. Dividing residual by IQR / 1.349 gives
# a robust z-score equivalent for a Gaussian distribution.
_IQR_TO_SIGMA: float = 1.349


def _locus_value_with_fallback(
    locus: ControlLocus,
    bin_key: tuple,
    column: str,
) -> tuple[float, int]:
    """Look up locus value at bin_key; fall back to coarser bins if sparse.

    Returns (value, n_controls_used). NaN with 0 if no useful fallback.
    The medians dataframe and the IQRs dataframe have disjoint column
    names, so the column name picks the table.
    """
    if column.endswith("_iqr"):
        table = locus.iqrs
    else:
        table = locus.medians

    for level in range(len(bin_key), 0, -1):
        partial_key = bin_key[:level] + (slice(None),) * (len(bin_key) - level)
        try:
            slice_df = table.loc[partial_key]
            counts_slice = locus.counts.loc[partial_key]
        except KeyError:
            continue
        if isinstance(slice_df, pd.Series):
            value = slice_df.get(column)
            if pd.notna(value) and counts_slice >= MIN_CONTROL_BIN_SIZE:
                return float(value), int(counts_slice)
        else:
            valid = counts_slice[counts_slice >= MIN_CONTROL_BIN_SIZE]
            if len(valid) == 0:
                continue
            value = slice_df.loc[valid.index, column].median()
            if pd.notna(value):
                return float(value), int(valid.sum())
    return float("nan"), 0


@dataclass(frozen=True)
class IRResidualScores:
    """Per-source W3 and W4 residual z-scores plus diagnostics."""

    scores: pd.DataFrame  # one row per input source


def score_ir_residuals(targets: pd.DataFrame, locus: ControlLocus) -> IRResidualScores:
    """Score the W3 and W4 color residuals for each target source.

    Each target is matched to its stratification bin in ``locus``. Where
    the bin is too sparse (fewer than ``MIN_CONTROL_BIN_SIZE`` controls),
    the score falls back to coarser bins (lat → distance → gmag → teff)
    and records the fallback level in ``locus_level_used``.
    """
    for col in (*_BIN_COLS, "w3_ks", "w4_ks", "gaia_dr3_source_id"):
        if col not in targets.columns:
            raise ValueError(f"targets missing column {col!r}")

    rows: list[dict] = []
    for _, src in targets.iterrows():
        bin_key = tuple(src[col] for col in _BIN_COLS)
        w3_median, n_w3 = _locus_value_with_fallback(locus, bin_key, "w3_ks_median")
        w4_median, n_w4 = _locus_value_with_fallback(locus, bin_key, "w4_ks_median")
        w3_iqr, _ = _locus_value_with_fallback(locus, bin_key, "w3_ks_iqr")
        w4_iqr, _ = _locus_value_with_fallback(locus, bin_key, "w4_ks_iqr")

        w3_z = _safe_z(src["w3_ks"], w3_median, w3_iqr)
        w4_z = _safe_z(src["w4_ks"], w4_median, w4_iqr)

        rows.append(
            {
                "gaia_dr3_source_id": int(src["gaia_dr3_source_id"]),
                "w3_ks_residual_z": w3_z,
                "w4_ks_residual_z": w4_z,
                "w3_locus_median": w3_median,
                "w3_locus_iqr": w3_iqr,
                "w4_locus_median": w4_median,
                "w4_locus_iqr": w4_iqr,
                "w3_n_controls_in_bin": n_w3,
                "w4_n_controls_in_bin": n_w4,
            }
        )
    return IRResidualScores(scores=pd.DataFrame(rows))


def _safe_z(value: float, median: float, iqr: float) -> float:
    if not (math.isfinite(value) and math.isfinite(median) and math.isfinite(iqr) and iqr > 0):
        return float("nan")
    sigma = iqr / _IQR_TO_SIGMA
    return float((value - median) / sigma)


def composite_ir_evidence_raw(scores: pd.DataFrame) -> pd.Series:
    """Return max(W3_z, W4_z) per source — raw IR evidence pre-calibration.

    Sources with a NaN W4 (no W4 detection) use the W3 residual alone.
    Empirical p-value calibration (``pharos.calibrate``) maps this raw
    score to a coverage-matched tail probability.
    """
    w3 = scores["w3_ks_residual_z"]
    w4 = scores["w4_ks_residual_z"]
    return np.fmax(w3.fillna(-math.inf), w4.fillna(-math.inf)).replace(
        -math.inf, math.nan
    )

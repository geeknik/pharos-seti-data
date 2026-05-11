"""IR-layer confounder vector for Pharos v0.1.

Each source receives a confounder probability vector P_IR whose components
are inspectable individually, plus a scalar ConfounderPenalty equal to the
inner product beta . P_IR. The beta weights are pre-registered
initialization values; calibration against the contaminant-positive
control set is scheduled for v0.1.1 (see model card).

Component definitions and beta weights mirror
pre_registration/v0.1_ir_benchmark.md §5. Changes require a versioned
superseding pre-registration document.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-registered beta weights for the IR-layer confounder vector.
# Source: pre_registration/v0.1_ir_benchmark.md §5.
# ---------------------------------------------------------------------------
BETA_WEIGHTS: dict[str, float] = {
    "blend": 2.0,
    "galaxy": 3.0,
    "qso": 3.0,
    "low_galactic_lat": 0.5,
    "hot_dog": 2.5,
    "bad_flag": 2.0,
    "nss": 1.0,
}

# Distance scale for the P_blend angular term. Pre-registered.
BLEND_ANGULAR_SCALE_ARCSEC: float = 1.5

# Galactic latitude thresholds for P_low_galactic_lat. Pre-registered.
LOW_LAT_FLOOR_DEG: float = 10.0
LOW_LAT_TAPER_DEG: float = 20.0

# HOT DOG heuristic thresholds. Pre-registered.
HOT_DOG_FAINT_G_THRESHOLD: float = 17.0  # mag
HOT_DOG_BRIGHT_W3_THRESHOLD: float = 12.0  # mag
HOT_DOG_BRIGHT_W4_THRESHOLD: float = 9.0  # mag


_COMPONENT_KEYS: tuple[str, ...] = tuple(BETA_WEIGHTS.keys())


@dataclass(frozen=True)
class ConfounderScores:
    """Per-source confounder probability vector and scalar penalty."""

    vector: pd.DataFrame  # gaia_dr3_source_id + one column per component
    penalty: pd.Series  # gaia_dr3_source_id-indexed Series of beta . P_IR


def _component_blend(df: pd.DataFrame) -> pd.Series:
    """Probability source's IR flux is blended with a WISE-confused neighbour.

    Combines two signals:
      - angular distance between the Gaia position and the AllWISE centroid
      - presence of additional AllWISE neighbours or mates in the crossmatch
    """
    ang = df.get("wise_xm_angular_distance")
    n_neighbours = df.get("wise_xm_n_neighbours")
    n_mates = df.get("wise_xm_n_mates")
    if ang is None or n_neighbours is None or n_mates is None:
        return pd.Series(np.zeros(len(df)), index=df.index)

    angular_component = 1.0 - np.exp(-ang.fillna(0.0) / BLEND_ANGULAR_SCALE_ARCSEC)
    crowded = ((n_neighbours.fillna(1) > 1) | (n_mates.fillna(0) > 0)).astype(float)
    return (angular_component * crowded).clip(lower=0.0, upper=1.0)


def _component_galaxy(df: pd.DataFrame) -> pd.Series:
    return df.get(
        "galaxy_probability", pd.Series(np.zeros(len(df)), index=df.index)
    ).fillna(0.0).clip(lower=0.0, upper=1.0)


def _component_qso(df: pd.DataFrame) -> pd.Series:
    return df.get(
        "qso_probability", pd.Series(np.zeros(len(df)), index=df.index)
    ).fillna(0.0).clip(lower=0.0, upper=1.0)


def _component_low_galactic_lat(df: pd.DataFrame) -> pd.Series:
    """Linear taper: 1.0 at |b| ≤ 10°, 0.0 at |b| ≥ 20°, linear in between."""
    b = df.get("galactic_b")
    if b is None:
        return pd.Series(np.zeros(len(df)), index=df.index)
    abs_b = b.abs()
    raw = (LOW_LAT_TAPER_DEG - abs_b) / (LOW_LAT_TAPER_DEG - LOW_LAT_FLOOR_DEG)
    return raw.clip(lower=0.0, upper=1.0).fillna(0.0)


def _component_hot_dog(df: pd.DataFrame) -> pd.Series:
    """Heuristic indicator for hot dust-obscured galaxy (HOT DOG) contamination.

    True HOT DOG identification needs an X-ray null match (Suazo et al.
    2024 §3.1 and the candidate G follow-up) — that requires an external
    catalog crossmatch which is deferred to v0.1.1. The v0.1 heuristic
    fires when:
      - Gaia G magnitude is faint (>= HOT_DOG_FAINT_G_THRESHOLD)
      - WISE W3 is bright (<= HOT_DOG_BRIGHT_W3_THRESHOLD)
        OR WISE W4 is bright (<= HOT_DOG_BRIGHT_W4_THRESHOLD)
      - Gaia DSC quasar probability is below 0.5 (a clear QSO match is
        covered by P_qso instead)
    """
    g = df.get("phot_g_mean_mag")
    w3 = df.get("w3mpro")
    w4 = df.get("w4mpro")
    qso = df.get("qso_probability")
    if g is None or w3 is None:
        return pd.Series(np.zeros(len(df)), index=df.index)

    faint_g = (g >= HOT_DOG_FAINT_G_THRESHOLD).astype(float)
    bright_w3 = (w3 <= HOT_DOG_BRIGHT_W3_THRESHOLD).astype(float)
    bright_w4 = (
        (w4 <= HOT_DOG_BRIGHT_W4_THRESHOLD).astype(float)
        if w4 is not None
        else pd.Series(np.zeros(len(df)), index=df.index)
    )
    not_qso = (
        (qso.fillna(0.0) < 0.5).astype(float)
        if qso is not None
        else pd.Series(np.ones(len(df)), index=df.index)
    )
    fired = faint_g * np.maximum(bright_w3, bright_w4) * not_qso
    return fired.clip(lower=0.0, upper=1.0).fillna(0.0)


def _component_bad_flag(df: pd.DataFrame) -> pd.Series:
    """AllWISE contamination flags or extended/blended-fit indicators."""
    cc = df.get("allwise_cc_flags")
    ext = df.get("allwise_ext_flg")
    nb = df.get("allwise_nb")

    cc_bad = pd.Series(np.zeros(len(df)), index=df.index)
    if cc is not None:
        cc_str = cc.fillna("0000").astype(str)
        # cc_flags is per-band; 'D','H','O','P' indicate diffraction, halo,
        # optical ghost, persistence contamination respectively.
        bad_chars = set("DHOP")
        cc_bad = cc_str.map(lambda s: any(ch in bad_chars for ch in s)).astype(float)

    ext_bad = (
        (ext.fillna(0).astype(int) > 0).astype(float)
        if ext is not None
        else pd.Series(np.zeros(len(df)), index=df.index)
    )
    nb_bad = (
        (nb.fillna(1).astype(int) > 1).astype(float)
        if nb is not None
        else pd.Series(np.zeros(len(df)), index=df.index)
    )
    fired = np.maximum(np.maximum(cc_bad, ext_bad), nb_bad)
    return pd.Series(fired, index=df.index).clip(lower=0.0, upper=1.0)


def _component_nss(df: pd.DataFrame) -> pd.Series:
    nss = df.get("non_single_star")
    if nss is None:
        return pd.Series(np.zeros(len(df)), index=df.index)
    return (nss.fillna(0).astype(int) > 0).astype(float)


_COMPONENT_FUNCTIONS = {
    "blend": _component_blend,
    "galaxy": _component_galaxy,
    "qso": _component_qso,
    "low_galactic_lat": _component_low_galactic_lat,
    "hot_dog": _component_hot_dog,
    "bad_flag": _component_bad_flag,
    "nss": _component_nss,
}


def compute_confounder_scores(df: pd.DataFrame) -> ConfounderScores:
    """Compute P_IR and beta . P_IR for each source."""
    if "gaia_dr3_source_id" not in df.columns:
        raise ValueError("input dataframe missing 'gaia_dr3_source_id' column")

    components = pd.DataFrame(index=df.index)
    components["gaia_dr3_source_id"] = df["gaia_dr3_source_id"].astype("int64")
    for key in _COMPONENT_KEYS:
        components[f"p_{key}"] = _COMPONENT_FUNCTIONS[key](df)

    weights = np.array([BETA_WEIGHTS[k] for k in _COMPONENT_KEYS], dtype=float)
    p_matrix = components[[f"p_{k}" for k in _COMPONENT_KEYS]].to_numpy(dtype=float)
    penalty_values = p_matrix @ weights

    penalty = pd.Series(
        penalty_values,
        index=components["gaia_dr3_source_id"].values,
        name="ir_confounder_penalty",
    )
    logger.info(
        "computed confounders: n_sources=%d, penalty median=%.3f, max=%.3f",
        len(penalty),
        float(np.median(penalty_values)) if len(penalty_values) else math.nan,
        float(np.max(penalty_values)) if len(penalty_values) else math.nan,
    )
    return ConfounderScores(vector=components, penalty=penalty)

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
# β weights for the IR-layer confounder vector.
#
# Pre-registered initialization values, per pre_registration/v0.1_ir_benchmark.md §5.
# When the v0.1.1 calibration artifact at controls/calibrated_betas_v0.1.1.yaml
# is present, BETA_WEIGHTS is overridden with the calibrated values at
# import time. Otherwise these v0.1 initialization weights are used.
# ---------------------------------------------------------------------------
_PRE_REG_V0_1_BETA: dict[str, float] = {
    "blend": 2.0,
    "galaxy": 3.0,
    "qso": 3.0,
    "low_galactic_lat": 0.5,
    "hot_dog": 2.5,
    "bad_flag": 2.0,
    "nss": 1.0,
    "wise_offset": 5.0,
}

BETA_WEIGHTS: dict[str, float] = dict(_PRE_REG_V0_1_BETA)


def _try_load_calibrated_betas() -> None:
    """If the v0.1.1 calibration artifact exists, override BETA_WEIGHTS.

    Searches upwards from this file for ``controls/calibrated_betas_v0.1.1.yaml``.
    Pure-Python import-time side effect; harmless when the file is absent.
    """
    import os
    import yaml as _yaml

    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):  # walk up to repo root
        candidate = os.path.join(here, "controls", "calibrated_betas_v0.1.1.yaml")
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as f:
                    payload = _yaml.safe_load(f)
                calibrated = payload.get("calibrated_betas")
                if isinstance(calibrated, dict):
                    BETA_WEIGHTS.update(
                        {k: float(v) for k, v in calibrated.items() if k in BETA_WEIGHTS}
                    )
                    logger.info(
                        "loaded v0.1.1 calibrated β from %s; %d components updated",
                        candidate, len(calibrated),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to load calibrated β from %s: %s", candidate, exc)
            return
        here = os.path.dirname(here)


_try_load_calibrated_betas()

# Distance scale for the P_blend angular term. Pre-registered.
BLEND_ANGULAR_SCALE_ARCSEC: float = 1.5

# Galactic latitude thresholds for P_low_galactic_lat. Pre-registered.
LOW_LAT_FLOOR_DEG: float = 10.0
LOW_LAT_TAPER_DEG: float = 20.0

# HOT DOG heuristic thresholds. Pre-registered.
HOT_DOG_FAINT_G_THRESHOLD: float = 17.0  # mag
HOT_DOG_BRIGHT_W3_THRESHOLD: float = 12.0  # mag
HOT_DOG_BRIGHT_W4_THRESHOLD: float = 9.0  # mag

# W1<->W3 photocentre offset scale (arcsec). Pre-registered.
# An offset of 6" yields P_wise_offset = 1.0; the Theissen & West (2017)
# quasar offset distribution has sigma_RA ~ 5.48", so a ~1 sigma RA
# outlier (e.g., candidate G at 5.59") maps to P ~ 0.93.
WISE_OFFSET_SCALE_ARCSEC: float = 6.0


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

    v0.1.1 (pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md §2.3):

      P_HOT_DOG = base_heuristic × (1 − X-ray_attenuation)

    The base heuristic fires when faint-G + bright-W3/W4 + low-DSC-QSO.
    The X-ray attenuation drops the probability to zero when the source
    has an X-ray detection in any covered catalog. If no X-ray columns
    are present in ``df`` (e.g., the quiet-negative population without
    a cross-match), the v0.1 heuristic is used unchanged.
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
    base = faint_g * np.maximum(bright_w3, bright_w4) * not_qso
    base = base.clip(lower=0.0, upper=1.0).fillna(0.0)

    xray_detected = df.get("xray_any_detection")
    xray_coverage = df.get("xray_coverage_count")
    if xray_detected is None or xray_coverage is None:
        return base
    # Attenuate to zero only when both detection and coverage are present.
    attenuation = (
        xray_detected.fillna(False).astype(bool) & (xray_coverage.fillna(0) > 0)
    ).astype(float)
    return (base * (1.0 - attenuation)).clip(lower=0.0, upper=1.0)


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


def _component_wise_offset(df: pd.DataFrame) -> pd.Series:
    """W1<->W3 photocentre offset as a contamination probability.

    Reads optional input columns ``w1_w3_offset_arcsec_ra`` and
    ``w1_w3_offset_arcsec_dec``. When neither is present, returns zeros
    (the general-population case where no per-band offset measurement
    is available in v0.1). When present, returns ``min(1, mag/6.0)``
    where mag is the quadrature sum of the two offsets in arcseconds.

    See pre_registration/v0.1_ir_benchmark.md §5 for the scale and the
    rationale (Theissen & West 2017 quasar offset distribution).
    """
    ra_off = df.get("w1_w3_offset_arcsec_ra")
    dec_off = df.get("w1_w3_offset_arcsec_dec")
    if ra_off is None and dec_off is None:
        return pd.Series(np.zeros(len(df)), index=df.index)
    ra = ra_off.fillna(0.0) if ra_off is not None else pd.Series(0.0, index=df.index)
    dec = dec_off.fillna(0.0) if dec_off is not None else pd.Series(0.0, index=df.index)
    magnitude = np.sqrt(ra**2 + dec**2)
    return (magnitude / WISE_OFFSET_SCALE_ARCSEC).clip(lower=0.0, upper=1.0)


_COMPONENT_FUNCTIONS = {
    "blend": _component_blend,
    "galaxy": _component_galaxy,
    "qso": _component_qso,
    "low_galactic_lat": _component_low_galactic_lat,
    "hot_dog": _component_hot_dog,
    "bad_flag": _component_bad_flag,
    "nss": _component_nss,
    "wise_offset": _component_wise_offset,
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

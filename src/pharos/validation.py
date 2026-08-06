"""Strict schemas and bounded-input validation for external catalog data.

External archive responses are untrusted.  This module deliberately performs
validation before joins, filtering, caching, or scientific interpretation.
Unknown columns are rejected rather than ignored so upstream schema drift
cannot silently change a released control population.
"""

from __future__ import annotations

from collections.abc import Iterable
from numbers import Real

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype

MAX_CLI_SOURCE_IDS = 10_000
MAX_NETWORK_SOURCE_CHUNK = 500
MAX_MATCHES_PER_SOURCE_CATALOG = 100
MAX_RAW_CONTROL_ROWS = 250_000
MAX_FINAL_CONTROL_ROWS = 250_000
MAX_EXCLUSION_ROWS = 5_000_000
TEFF_MIN_K = 1.0
TEFF_MAX_K = 100_000.0
BP_RP_G_MAG_BIN_WIDTH = 0.5
BP_RP_EXCESS_MAX_DELTA = 0.1
WISE_MAG_ERROR_TO_SNR = 1.0857
# TAP evaluates the same arithmetic in double precision; these tolerances allow
# only Parquet float round-tripping, not independently supplied SNR values.
WISE_SNR_CONSISTENCY_RTOL = 1e-9
WISE_SNR_CONSISTENCY_ATOL = 1e-12
COVERAGE_CLASS_CUTS: dict[str, float] = {
    "parallax_over_error_min": 5.0,
    "g_mag_max": 18.0,
    "distance_pc_max": 200.0,
    "allwise_angular_distance_max_arcsec": 3.0,
    "w1_snr_min": 5.0,
    "w2_snr_min": 5.0,
    "w3_snr_min": 3.0,
    "w4_snr_min": 2.0,
}

GAIA_RESPONSE_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "ra",
    "dec",
    "galactic_l",
    "galactic_b",
    "parallax",
    "parallax_error",
    "parallax_over_error",
    "pmra",
    "pmdec",
    "ruwe",
    "astrometric_excess_noise",
    "astrometric_excess_noise_sig",
    "phot_g_mean_mag",
    "phot_bp_rp_excess_factor",
    "ipd_frac_multi_peak",
    "ipd_frac_odd_win",
    "duplicated_source",
    "non_single_star",
    "qso_probability",
    "galaxy_probability",
    "teff_gspphot",
    "logg_gspphot",
    "distance_gspphot",
    "ag_gspphot",
)

ALLWISE_RESPONSE_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "wise_xm_angular_distance",
    "wise_xm_n_neighbours",
    "wise_xm_n_mates",
    "wise_xm_flag",
    "allwise_designation",
    "w1mpro",
    "w1mpro_error",
    "w1snr",
    "w2mpro",
    "w2mpro_error",
    "w2snr",
    "w3mpro",
    "w3mpro_error",
    "w3snr",
    "w4mpro",
    "w4mpro_error",
    "w4snr",
    "allwise_cc_flags",
    "allwise_ext_flg",
)

TMASS_RESPONSE_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "tmass_xm_angular_distance",
    "tmass_designation",
    "tmass_j_m",
    "tmass_j_msigcom",
    "tmass_h_m",
    "tmass_h_msigcom",
    "tmass_ks_m",
    "tmass_ks_msigcom",
)

JOINED_SOURCE_COLUMNS: tuple[str, ...] = (
    GAIA_RESPONSE_COLUMNS + ALLWISE_RESPONSE_COLUMNS[1:] + TMASS_RESPONSE_COLUMNS[1:]
)

CONTROL_DERIVED_COLUMNS: tuple[str, ...] = (
    "gmag_bin_lower",
    "bp_rp_excess_bin_median",
    "bp_rp_excess_delta",
)

CONTROL_ARTIFACT_COLUMNS: tuple[str, ...] = JOINED_SOURCE_COLUMNS + CONTROL_DERIVED_COLUMNS

EXCLUSION_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "exclusion_catalog",
    "exclusion_class",
    "matched_object_id",
    "matched_otype",
    "angular_distance_arcsec",
    "catalog_release",
)

SIMBAD_RESPONSE_COLUMNS: tuple[str, ...] = (
    "gaia_dr3_source_id",
    "matched_object_id",
    "matched_otype",
    "angular_distance_arcsec",
)

CHEN_RESPONSE_COLUMNS: tuple[str, ...] = ("_RA", "_DE", "Name")


def validate_exact_columns(
    frame: pd.DataFrame,
    expected: Iterable[str],
    *,
    context: str,
) -> None:
    """Reject missing, unexpected, duplicated, or reordered columns."""
    expected_tuple = tuple(expected)
    actual = tuple(str(column) for column in frame.columns)
    if len(actual) != len(set(actual)):
        raise ValueError(f"{context}: duplicate column names are forbidden")
    if actual != expected_tuple:
        missing = sorted(set(expected_tuple) - set(actual))
        unexpected = sorted(set(actual) - set(expected_tuple))
        raise ValueError(
            f"{context}: schema mismatch; missing={missing}, unexpected={unexpected}, "
            "or column order changed"
        )


def _require_numeric(frame: pd.DataFrame, columns: Iterable[str], *, context: str) -> None:
    for column in columns:
        if not is_numeric_dtype(frame[column].dtype):
            raise TypeError(f"{context}: {column} must be numeric")


def _require_finite(frame: pd.DataFrame, columns: Iterable[str], *, context: str) -> None:
    for column in columns:
        series = frame[column]
        values = series.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{context}: {column} contains non-finite values")


def _require_between(
    frame: pd.DataFrame,
    column: str,
    lower: float,
    upper: float,
    *,
    context: str,
    inclusive_upper: bool = True,
) -> None:
    values = frame[column].dropna()
    upper_bad = values > upper if inclusive_upper else values >= upper
    if ((values < lower) | upper_bad).any():
        bracket = "]" if inclusive_upper else ")"
        raise ValueError(f"{context}: {column} outside [{lower}, {upper}{bracket}")


def _validate_source_id_column(
    frame: pd.DataFrame,
    *,
    context: str,
    unique: bool,
) -> None:
    ids = frame["gaia_dr3_source_id"]
    if not is_integer_dtype(ids.dtype) or is_bool_dtype(ids.dtype):
        raise TypeError(f"{context}: gaia_dr3_source_id must use an integer dtype")
    if ids.isna().any() or (ids <= 0).any():
        raise ValueError(f"{context}: source identifiers must be positive and non-null")
    if unique and ids.duplicated().any():
        raise ValueError(f"{context}: duplicate source identifiers are forbidden")


def validate_gaia_response(frame: pd.DataFrame, *, requested_rows: int) -> None:
    context = "Gaia response"
    validate_exact_columns(frame, GAIA_RESPONSE_COLUMNS, context=context)
    if requested_rows < 1 or requested_rows > MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError(f"{context}: requested row count exceeds registered network bound")
    if len(frame) > requested_rows:
        raise ValueError(f"{context}: returned more rows than requested")
    _validate_source_id_column(frame, context=context, unique=True)
    _require_numeric(
        frame,
        (
            "ra",
            "dec",
            "galactic_l",
            "galactic_b",
            "parallax",
            "parallax_error",
            "parallax_over_error",
            "ruwe",
            "phot_g_mean_mag",
            "phot_bp_rp_excess_factor",
            "qso_probability",
            "galaxy_probability",
            "teff_gspphot",
        ),
        context=context,
    )
    _require_finite(
        frame,
        (
            "ra",
            "dec",
            "galactic_l",
            "galactic_b",
            "parallax",
            "parallax_error",
            "parallax_over_error",
            "ruwe",
            "phot_g_mean_mag",
            "phot_bp_rp_excess_factor",
            "qso_probability",
            "galaxy_probability",
            "teff_gspphot",
        ),
        context=context,
    )
    _require_between(frame, "ra", 0.0, 360.0, context=context, inclusive_upper=False)
    _require_between(frame, "dec", -90.0, 90.0, context=context)
    _require_between(frame, "galactic_l", 0.0, 360.0, context=context, inclusive_upper=False)
    _require_between(frame, "galactic_b", -90.0, 90.0, context=context)
    if (frame["parallax"] <= 0).any() or (frame["parallax_over_error"] < 5.0).any():
        raise ValueError(f"{context}: parallax coverage cut violated")
    if (frame["parallax"] < 5.0).any() or (frame["parallax_error"] <= 0.0).any():
        raise ValueError(f"{context}: distance/error coverage cut violated")
    if (frame["phot_g_mean_mag"] > 18.0).any() or (frame["ruwe"] >= 1.2).any():
        raise ValueError(f"{context}: quiet-negative quality cut violated")
    if (frame["galactic_b"].abs() <= 20.0).any():
        raise ValueError(f"{context}: Galactic latitude cut violated")
    for column in ("qso_probability", "galaxy_probability"):
        _require_between(frame, column, 0.0, 0.1, context=context, inclusive_upper=False)
    if (
        (frame["teff_gspphot"] < TEFF_MIN_K)
        | (frame["teff_gspphot"] > TEFF_MAX_K)
    ).any():
        raise ValueError(f"{context}: effective temperature eligibility cut violated")
    if not is_bool_dtype(frame["duplicated_source"].dtype):
        raise TypeError(f"{context}: duplicated_source must use a boolean dtype")
    if frame["duplicated_source"].any() or (frame["non_single_star"] != 0).any():
        raise ValueError(f"{context}: duplicated or non-single source escaped query")


def validate_allwise_response(frame: pd.DataFrame, *, requested_ids: set[int]) -> None:
    context = "AllWISE response"
    validate_exact_columns(frame, ALLWISE_RESPONSE_COLUMNS, context=context)
    if len(requested_ids) > MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError(f"{context}: request exceeds registered network bound")
    if len(frame) > len(requested_ids):
        raise ValueError(f"{context}: response has more rows than requested identifiers")
    _validate_source_id_column(frame, context=context, unique=True)
    if not set(frame["gaia_dr3_source_id"].astype(int)).issubset(requested_ids):
        raise ValueError(f"{context}: response contains an unrequested source identifier")
    numeric = (
        "wise_xm_angular_distance",
        "wise_xm_n_neighbours",
        "wise_xm_n_mates",
        "wise_xm_flag",
        "w1mpro",
        "w1mpro_error",
        "w1snr",
        "w2mpro",
        "w2mpro_error",
        "w2snr",
        "w3mpro",
        "w3mpro_error",
        "w3snr",
        "w4mpro",
        "w4mpro_error",
        "w4snr",
        "allwise_ext_flg",
    )
    _require_numeric(frame, numeric, context=context)
    _require_finite(
        frame,
        tuple(column for column in numeric if not column.startswith("w4")),
        context=context,
    )
    _require_between(frame, "wise_xm_angular_distance", 0.0, 1.5, context=context)
    if (frame["wise_xm_n_neighbours"] != 1).any() or (frame["wise_xm_n_mates"] != 0).any():
        raise ValueError(f"{context}: crossmatch multiplicity cut violated")
    for band in ("w1", "w2", "w3"):
        minimum_snr = COVERAGE_CLASS_CUTS[f"{band}_snr_min"]
        maximum = WISE_MAG_ERROR_TO_SNR / minimum_snr
        errors = frame[f"{band}mpro_error"]
        snr = frame[f"{band}snr"]
        if ((errors <= 0.0) | (errors > maximum)).any():
            raise ValueError(
                f"{context}: {band.upper()} uncertainty violates the registered "
                f"(0, {maximum:.6f}] gate"
            )
        if (snr < minimum_snr).any():
            raise ValueError(f"{context}: {band.upper()} SNR cut violated")
        expected_snr = WISE_MAG_ERROR_TO_SNR / errors
        if not np.isclose(
            snr.to_numpy(dtype=float),
            expected_snr.to_numpy(dtype=float),
            rtol=WISE_SNR_CONSISTENCY_RTOL,
            atol=WISE_SNR_CONSISTENCY_ATOL,
        ).all():
            raise ValueError(f"{context}: {band.upper()} SNR is inconsistent with its uncertainty")
    w4 = frame[["w4mpro", "w4mpro_error", "w4snr"]]
    if (~(w4.isna().all(axis=1) | w4.notna().all(axis=1))).any():
        raise ValueError(f"{context}: partial W4 photometry is forbidden")
    covered_w4 = w4.notna().all(axis=1)
    if covered_w4.any():
        values = w4.loc[covered_w4].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{context}: covered W4 photometry must be finite")
        covered = w4.loc[covered_w4]
        if (covered["w4mpro_error"] <= 0.0).any():
            raise ValueError(f"{context}: covered W4 uncertainty must be positive")
        expected_w4_snr = WISE_MAG_ERROR_TO_SNR / covered["w4mpro_error"]
        if not np.isclose(
            covered["w4snr"].to_numpy(dtype=float),
            expected_w4_snr.to_numpy(dtype=float),
            rtol=WISE_SNR_CONSISTENCY_RTOL,
            atol=WISE_SNR_CONSISTENCY_ATOL,
        ).all():
            raise ValueError(f"{context}: W4 SNR is inconsistent with its uncertainty")
        if (covered["w4snr"] < COVERAGE_CLASS_CUTS["w4_snr_min"]).any():
            raise ValueError(f"{context}: covered W4 SNR cut violated")
    designation = frame["allwise_designation"]
    if designation.isna().any() or (designation.astype(str).str.len() == 0).any():
        raise ValueError(f"{context}: AllWISE designation must be non-empty")
    flags = frame["allwise_cc_flags"].dropna().astype(str)
    if not flags.isin({"0000"}).all():
        raise ValueError(f"{context}: contamination flags escaped query")
    if not frame["allwise_ext_flg"].dropna().isin({0}).all():
        raise ValueError(f"{context}: extended-source flags escaped query")


def normalize_optional_w4(frame: pd.DataFrame) -> pd.DataFrame:
    """Canonicalize catalog-missing or valid sub-threshold W4 to absence.

    The frozen coverage class requires W1--W3 but makes W4 optional and scores
    it only at SNR >= 2. Gaia can return incomplete W4 fields, and the derived
    SNR projection is absent when the uncertainty is absent. At this
    untrusted-response boundary, catalog-defined wholly absent or partial W4
    rows are represented as an uncovered W4 channel. A complete, finite,
    positive-uncertainty, internally consistent triple is also uncovered when
    it is below the registered SNR threshold. The source is retained because
    W4 is optional.

    Every present member is validated before missingness normalization.
    Malformed partial or complete rows are rejected rather than laundered into
    missing data: nonnumeric or non-finite values, nonpositive uncertainty,
    negative SNR, and an error/SNR pair inconsistent with
    ``1.0857 / uncertainty`` all fail closed.

    This function is deliberately not used by artifact loaders. Persisted
    artifacts must already contain the canonical representation, and the
    strict validators continue to reject partial or forged W4 triples.
    """
    required = ("w4mpro", "w4mpro_error", "w4snr")
    if any(column not in frame.columns for column in required):
        raise ValueError("W4 normalization requires the complete W4 column triple")
    out = frame.copy()
    w4 = out.loc[:, required]
    present = w4.notna()
    for column in required:
        values = w4.loc[present[column], column]
        if not values.map(
            lambda value: isinstance(value, Real)
            and not isinstance(value, (bool, np.bool_))
        ).all():
            raise TypeError(f"W4 response normalization: {column} must be numeric")
    numeric = w4.apply(pd.to_numeric, errors="coerce")
    error_present = present["w4mpro_error"]
    if (numeric.loc[error_present, "w4mpro_error"] <= 0.0).any():
        raise ValueError("W4 response normalization: present W4 uncertainty must be positive")
    present_values = numeric.to_numpy(dtype=float)[present.to_numpy(dtype=bool)]
    if not np.isfinite(present_values).all():
        raise ValueError("W4 response normalization: present W4 photometry must be finite")

    snr_present = present["w4snr"]
    if (numeric.loc[snr_present, "w4snr"] < 0.0).any():
        raise ValueError("W4 response normalization: present W4 SNR must be non-negative")
    error_and_snr = error_present & snr_present
    expected_snr = WISE_MAG_ERROR_TO_SNR / numeric.loc[error_and_snr, "w4mpro_error"]
    if not np.isclose(
        numeric.loc[error_and_snr, "w4snr"].to_numpy(dtype=float),
        expected_snr.to_numpy(dtype=float),
        rtol=WISE_SNR_CONSISTENCY_RTOL,
        atol=WISE_SNR_CONSISTENCY_ATOL,
    ).all():
        raise ValueError("W4 response normalization: present W4 SNR is inconsistent")

    complete = present.all(axis=1)
    out.loc[~complete, list(required)] = np.nan
    subthreshold = complete & (numeric["w4snr"] < COVERAGE_CLASS_CUTS["w4_snr_min"])
    out.loc[subthreshold[subthreshold].index, list(required)] = np.nan
    return out


def validate_tmass_response(frame: pd.DataFrame, *, requested_ids: set[int]) -> None:
    context = "2MASS response"
    validate_exact_columns(frame, TMASS_RESPONSE_COLUMNS, context=context)
    if len(requested_ids) > MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError(f"{context}: request exceeds registered network bound")
    if len(frame) > len(requested_ids):
        raise ValueError(f"{context}: response has more rows than requested identifiers")
    _validate_source_id_column(frame, context=context, unique=True)
    if not set(frame["gaia_dr3_source_id"].astype(int)).issubset(requested_ids):
        raise ValueError(f"{context}: response contains an unrequested source identifier")
    numeric = (
        "tmass_xm_angular_distance",
        "tmass_j_m",
        "tmass_j_msigcom",
        "tmass_h_m",
        "tmass_h_msigcom",
        "tmass_ks_m",
        "tmass_ks_msigcom",
    )
    _require_numeric(frame, numeric, context=context)
    _require_finite(
        frame,
        ("tmass_xm_angular_distance", "tmass_ks_m", "tmass_ks_msigcom"),
        context=context,
    )
    _require_between(frame, "tmass_xm_angular_distance", 0.0, 1.5, context=context)
    if (frame["tmass_ks_msigcom"] <= 0.0).any():
        raise ValueError(f"{context}: 2MASS Ks uncertainty must be positive")
    designation = frame["tmass_designation"]
    if designation.isna().any() or (designation.astype(str).str.len() == 0).any():
        raise ValueError(f"{context}: 2MASS designation must be non-empty")


def validate_joined_source_frame(frame: pd.DataFrame, *, maximum_rows: int) -> None:
    """Re-run every registered Gaia/AllWISE/2MASS gate on joined rows."""
    context = "joined quiet-negative sources"
    validate_exact_columns(frame, JOINED_SOURCE_COLUMNS, context=context)
    if len(frame) > maximum_rows:
        raise ValueError(f"{context}: row count exceeds registered bound")
    if frame["gaia_dr3_source_id"].duplicated().any():
        raise ValueError(f"{context}: duplicate source identifiers are forbidden")
    for start in range(0, len(frame), MAX_NETWORK_SOURCE_CHUNK):
        chunk = frame.iloc[start : start + MAX_NETWORK_SOURCE_CHUNK]
        if chunk.empty:
            continue
        validate_gaia_response(chunk.loc[:, GAIA_RESPONSE_COLUMNS], requested_rows=len(chunk))
        requested_ids = set(chunk["gaia_dr3_source_id"].astype(int))
        validate_allwise_response(
            chunk.loc[:, ALLWISE_RESPONSE_COLUMNS], requested_ids=requested_ids
        )
        validate_tmass_response(chunk.loc[:, TMASS_RESPONSE_COLUMNS], requested_ids=requested_ids)


def validate_control_artifact(frame: pd.DataFrame, *, minimum_rows: int) -> None:
    context = "quiet-negative artifact"
    validate_exact_columns(frame, CONTROL_ARTIFACT_COLUMNS, context=context)
    if len(frame) < minimum_rows:
        raise ValueError(f"{context}: requires at least {minimum_rows} rows; got {len(frame)}")
    if len(frame) > MAX_FINAL_CONTROL_ROWS:
        raise ValueError(f"{context}: row count exceeds registered bound")
    validate_joined_source_frame(
        frame.loc[:, JOINED_SOURCE_COLUMNS], maximum_rows=MAX_FINAL_CONTROL_ROWS
    )
    _require_finite(
        frame,
        (
            "ra",
            "dec",
            "gmag_bin_lower",
            "bp_rp_excess_bin_median",
            "bp_rp_excess_delta",
        ),
        context=context,
    )
    _require_between(frame, "ra", 0.0, 360.0, context=context, inclusive_upper=False)
    _require_between(frame, "dec", -90.0, 90.0, context=context)
    if (frame["bp_rp_excess_delta"].abs() > 0.1 + 1e-12).any():
        raise ValueError(f"{context}: BP/RP excess cut violated")
    expected_lower = np.floor(frame["phot_g_mean_mag"] / 0.5) * 0.5
    if not np.allclose(frame["gmag_bin_lower"], expected_lower, rtol=0.0, atol=1e-12):
        raise ValueError(f"{context}: BP/RP magnitude-bin assignment mismatch")
    expected_delta = frame["phot_bp_rp_excess_factor"] - frame["bp_rp_excess_bin_median"]
    if not np.allclose(frame["bp_rp_excess_delta"], expected_delta, rtol=0.0, atol=1e-12):
        raise ValueError(f"{context}: BP/RP residual relationship mismatch")
    medians_per_bin = frame.groupby("gmag_bin_lower", observed=True)[
        "bp_rp_excess_bin_median"
    ].nunique(dropna=False)
    if (medians_per_bin != 1).any():
        raise ValueError(f"{context}: BP/RP bin median is not constant within a bin")


def derive_bp_rp_controls(candidates: pd.DataFrame) -> pd.DataFrame:
    """Recompute the frozen BP/RP cut from the complete parent candidate table."""
    validate_joined_source_frame(candidates, maximum_rows=MAX_RAW_CONTROL_ROWS)
    out = candidates.copy()
    out["gmag_bin_lower"] = (
        np.floor(out["phot_g_mean_mag"] / BP_RP_G_MAG_BIN_WIDTH)
        * BP_RP_G_MAG_BIN_WIDTH
    )
    out["bp_rp_excess_bin_median"] = out.groupby(
        "gmag_bin_lower", observed=True
    )["phot_bp_rp_excess_factor"].transform("median")
    out["bp_rp_excess_delta"] = (
        out["phot_bp_rp_excess_factor"] - out["bp_rp_excess_bin_median"]
    )
    out = out[out["bp_rp_excess_delta"].abs() <= BP_RP_EXCESS_MAX_DELTA].copy()
    out.reset_index(drop=True, inplace=True)
    validate_exact_columns(out, CONTROL_ARTIFACT_COLUMNS, context="derived BP/RP controls")
    return out


def validate_control_derivation(
    raw_candidates: pd.DataFrame,
    controls: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> None:
    """Prove the released controls equal BP/RP survivors minus exact exclusions."""
    expected = derive_bp_rp_controls(raw_candidates)
    excluded_ids = set(exclusions["gaia_dr3_source_id"].astype(int))
    expected = expected[
        ~expected["gaia_dr3_source_id"].astype(int).isin(excluded_ids)
    ].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            controls.reset_index(drop=True),
            expected,
            check_exact=False,
            rtol=1e-7,
            atol=1e-12,
        )
    except AssertionError as exc:
        raise ValueError(
            "quiet-negative controls do not match the registered parent-population derivation"
        ) from exc


def validate_exclusions(frame: pd.DataFrame) -> None:
    context = "external exclusions"
    validate_exact_columns(frame, EXCLUSION_COLUMNS, context=context)
    if frame.empty:
        return
    if len(frame) > MAX_EXCLUSION_ROWS:
        raise ValueError(f"{context}: row count exceeds registered bound")
    _validate_source_id_column(frame, context=context, unique=False)
    _require_numeric(frame, ("angular_distance_arcsec",), context=context)
    _require_finite(frame, ("angular_distance_arcsec",), context=context)
    _require_between(frame, "angular_distance_arcsec", 0.0, 30.0, context=context)
    if not frame["exclusion_catalog"].isin({"SIMBAD", "Chen2014"}).all():
        raise ValueError(f"{context}: unknown catalog")
    if not frame["exclusion_class"].isin({"YSO", "AGN", "debris_disk"}).all():
        raise ValueError(f"{context}: unknown exclusion class")
    if frame.duplicated(subset=list(EXCLUSION_COLUMNS)).any():
        raise ValueError(f"{context}: residual exact duplicate tuple is forbidden")
    counts = frame.groupby(["gaia_dr3_source_id", "exclusion_catalog"], dropna=False).size()
    if (counts > MAX_MATCHES_PER_SOURCE_CATALOG).any():
        raise ValueError(f"{context}: retained-match bound exceeded")

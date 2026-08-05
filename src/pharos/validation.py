"""Strict schemas and bounded-input validation for external catalog data.

External archive responses are untrusted.  This module deliberately performs
validation before joins, filtering, caching, or scientific interpretation.
Unknown columns are rejected rather than ignored so upstream schema drift
cannot silently change a released control population.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype

MAX_CLI_SOURCE_IDS = 10_000
MAX_NETWORK_SOURCE_CHUNK = 500
MAX_MATCHES_PER_SOURCE_CATALOG = 100

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
    GAIA_RESPONSE_COLUMNS
    + ALLWISE_RESPONSE_COLUMNS[1:]
    + TMASS_RESPONSE_COLUMNS[1:]
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
        ),
        context=context,
    )
    _require_between(frame, "ra", 0.0, 360.0, context=context, inclusive_upper=False)
    _require_between(frame, "dec", -90.0, 90.0, context=context)
    _require_between(frame, "galactic_l", 0.0, 360.0, context=context, inclusive_upper=False)
    _require_between(frame, "galactic_b", -90.0, 90.0, context=context)
    if (frame["parallax"] <= 0).any() or (frame["parallax_over_error"] < 5.0).any():
        raise ValueError(f"{context}: parallax coverage cut violated")
    if (frame["phot_g_mean_mag"] > 18.0).any() or (frame["ruwe"] >= 1.2).any():
        raise ValueError(f"{context}: quiet-negative quality cut violated")
    if (frame["galactic_b"].abs() <= 20.0).any():
        raise ValueError(f"{context}: Galactic latitude cut violated")
    for column in ("qso_probability", "galaxy_probability"):
        _require_between(frame, column, 0.0, 0.1, context=context, inclusive_upper=False)
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
        "allwise_ext_flg",
    )
    _require_numeric(frame, numeric, context=context)
    _require_finite(frame, numeric, context=context)
    _require_between(frame, "wise_xm_angular_distance", 0.0, 1.5, context=context)
    if (frame["wise_xm_n_neighbours"] != 1).any() or (frame["wise_xm_n_mates"] != 0).any():
        raise ValueError(f"{context}: crossmatch multiplicity cut violated")
    if (frame["w1snr"] < 5.0).any() or (frame["w2snr"] < 5.0).any():
        raise ValueError(f"{context}: W1/W2 SNR cut violated")
    if (frame["w3snr"] < 3.0).any():
        raise ValueError(f"{context}: W3 SNR cut violated")
    flags = frame["allwise_cc_flags"].dropna().astype(str)
    if not flags.isin({"0000"}).all():
        raise ValueError(f"{context}: contamination flags escaped query")
    if not frame["allwise_ext_flg"].dropna().isin({0}).all():
        raise ValueError(f"{context}: extended-source flags escaped query")


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


def validate_control_artifact(frame: pd.DataFrame, *, minimum_rows: int) -> None:
    context = "quiet-negative artifact"
    validate_exact_columns(frame, CONTROL_ARTIFACT_COLUMNS, context=context)
    if len(frame) < minimum_rows:
        raise ValueError(f"{context}: requires at least {minimum_rows} rows; got {len(frame)}")
    _validate_source_id_column(frame, context=context, unique=True)
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


def validate_exclusions(frame: pd.DataFrame) -> None:
    context = "external exclusions"
    validate_exact_columns(frame, EXCLUSION_COLUMNS, context=context)
    if frame.empty:
        return
    _validate_source_id_column(frame, context=context, unique=False)
    _require_numeric(frame, ("angular_distance_arcsec",), context=context)
    _require_finite(frame, ("angular_distance_arcsec",), context=context)
    _require_between(frame, "angular_distance_arcsec", 0.0, 30.0, context=context)
    if not frame["exclusion_catalog"].isin({"SIMBAD", "Chen2014"}).all():
        raise ValueError(f"{context}: unknown catalog")
    if not frame["exclusion_class"].isin({"YSO", "AGN", "debris_disk"}).all():
        raise ValueError(f"{context}: unknown exclusion class")
    counts = frame.groupby(["gaia_dr3_source_id", "exclusion_catalog"], dropna=False).size()
    if (counts > MAX_MATCHES_PER_SOURCE_CATALOG).any():
        raise ValueError(f"{context}: retained-match bound exceeded")

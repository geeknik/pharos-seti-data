"""Gaia DR3 + AllWISE + 2MASS source acquisition for Pharos v0.1.

This module is responsible for two concrete jobs:

1. Building and executing the pre-registered ADQL query for the
   quiet-negative control population (pre_registration/v0.1_ir_benchmark.md §6).
2. Fetching the Gaia DR3 + AllWISE + 2MASS row set for an explicit list of
   target source IDs (e.g., the seven Hephaistos candidates in
   controls/hephaistos.yaml).

Network access is encapsulated in ``fetch_quiet_negative_controls`` and
``fetch_targets_by_source_id``. Everything else in this module is pure and
deterministic, which makes the ADQL construction unit-testable without
touching the Gaia archive.

The constants at the top of the file are exact mirrors of the pre-registered
cuts. Changing one of these constants requires a versioned superseding
pre-registration document, not an inline edit — see
``pre_registration/v0.1_ir_benchmark.md`` §10.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

# Credential file paths checked in order. The first existing, mode-600
# file is used; everything else falls back to anonymous access. Path
# resolution is centralised here so it stays out of the call paths.
_GAIA_CREDENTIALS_PATHS: tuple[Path, ...] = (
    Path.home() / ".config" / "pharos" / "gaia_credentials.txt",
)

# Module-level flag so we attempt login at most once per process. The
# value is one of {"unknown", "anonymous", "authenticated"}.
_login_state: str = "unknown"

# ---------------------------------------------------------------------------
# Gaia archive table names (Gaia DR3 release).
# ---------------------------------------------------------------------------
GAIA_SOURCE_TABLE = "gaiadr3.gaia_source"
ALLWISE_XMATCH_TABLE = "gaiadr3.allwise_best_neighbour"
ALLWISE_PHOTO_TABLE = "gaiadr1.allwise_original_valid"
TMASS_XMATCH_TABLE = "gaiadr3.tmass_psc_xsc_best_neighbour"
TMASS_PHOTO_TABLE = "gaiadr1.tmass_original_valid"

# ---------------------------------------------------------------------------
# Pre-registered cuts for the WISE-only coverage class.
# Source: pre_registration/v0.1_ir_benchmark.md §2.
# ---------------------------------------------------------------------------
COVERAGE_CLASS_CUTS: dict[str, float] = {
    "parallax_over_error_min": 5.0,
    "g_mag_max": 18.0,
    "distance_pc_max": 200.0,
    "allwise_angular_distance_max_arcsec": 3.0,
    "w1_snr_min": 5.0,
    "w2_snr_min": 5.0,
    "w3_snr_min": 3.0,
}

# ---------------------------------------------------------------------------
# Pre-registered additional cuts for the quiet-negative control population.
# Source: pre_registration/v0.1_ir_benchmark.md §6.
# ---------------------------------------------------------------------------
QUIET_NEGATIVE_CUTS: dict[str, float] = {
    "ruwe_max": 1.2,
    "galaxy_prob_max": 0.10,
    "quasar_prob_max": 0.10,
    "allwise_n_neighbours": 1,
    "allwise_n_mates": 0,
    "allwise_angular_distance_max_arcsec": 1.5,
    "galactic_latitude_min_deg": 20.0,
    "tmass_angular_distance_max_arcsec": 1.5,
}

# Columns selected from the join. The set is fixed by pre-registration: do
# not add fields here without bumping the pre-registration version.
_SELECT_COLUMNS: tuple[str, ...] = (
    # Gaia astrometry and identity
    "gs.source_id AS gaia_dr3_source_id",
    "gs.ra",
    "gs.dec",
    "gs.l AS galactic_l",
    "gs.b AS galactic_b",
    "gs.parallax",
    "gs.parallax_error",
    "gs.parallax_over_error",
    "gs.pmra",
    "gs.pmdec",
    "gs.ruwe",
    "gs.astrometric_excess_noise",
    "gs.astrometric_excess_noise_sig",
    # Gaia photometry and quality flags
    "gs.phot_g_mean_mag",
    "gs.phot_bp_rp_excess_factor",
    "gs.ipd_frac_multi_peak",
    "gs.ipd_frac_odd_win",
    "gs.duplicated_source",
    "gs.non_single_star",
    "gs.classprob_dsc_combmod_quasar AS qso_probability",
    "gs.classprob_dsc_combmod_galaxy AS galaxy_probability",
    # GSP-Phot astrophysical parameters (parallax-dependent — do not use as
    # an independent anomaly modality; see manuscript §3.1).
    "gs.teff_gspphot",
    "gs.logg_gspphot",
    "gs.distance_gspphot",
    "gs.ag_gspphot",
    # AllWISE crossmatch metadata (drives the IR confounder model)
    "awbn.angular_distance AS wise_xm_angular_distance",
    "awbn.number_of_neighbours AS wise_xm_n_neighbours",
    "awbn.number_of_mates AS wise_xm_n_mates",
    "awbn.xm_flag AS wise_xm_flag",
    # AllWISE photometry. The Gaia-hosted AllWISE table does not expose
    # per-band SNR or nb columns; SNR is derived from the magnitude
    # uncertainty via Pogson's law (snr ~= 1.0857 / mag_error).
    "aw.designation AS allwise_designation",
    "aw.w1mpro",
    "aw.w1mpro_error",
    "(1.0857 / aw.w1mpro_error) AS w1snr",
    "aw.w2mpro",
    "aw.w2mpro_error",
    "(1.0857 / aw.w2mpro_error) AS w2snr",
    "aw.w3mpro",
    "aw.w3mpro_error",
    "(1.0857 / aw.w3mpro_error) AS w3snr",
    "aw.w4mpro",
    "aw.w4mpro_error",
    "(1.0857 / aw.w4mpro_error) AS w4snr",
    "aw.cc_flags AS allwise_cc_flags",
    "aw.ext_flag AS allwise_ext_flg",
    # 2MASS crossmatch and photometry (NIR anchor for the photosphere fit)
    "tmbn.angular_distance AS tmass_xm_angular_distance",
    "tm.designation AS tmass_designation",
    "tm.j_m AS tmass_j_m",
    "tm.j_msigcom AS tmass_j_msigcom",
    "tm.h_m AS tmass_h_m",
    "tm.h_msigcom AS tmass_h_msigcom",
    "tm.ks_m AS tmass_ks_m",
    "tm.ks_msigcom AS tmass_ks_msigcom",
)


@dataclass(frozen=True)
class SourceQueryResult:
    """The result of a Gaia TAP query plus its provenance.

    ``query_hash`` is the SHA-256 of the exact ADQL text submitted. The
    cache key for each query is this hash, which means any change to the
    pre-registered cuts invalidates every cache entry.
    """

    sources: pd.DataFrame
    query_text: str
    query_hash: str
    n_sources: int


def _hash_query(query_text: str) -> str:
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()


def _build_select_clause() -> str:
    return ",\n  ".join(_SELECT_COLUMNS)


def _build_join_clause() -> str:
    return (
        f"FROM {GAIA_SOURCE_TABLE} AS gs\n"
        f"  LEFT JOIN {ALLWISE_XMATCH_TABLE} AS awbn ON gs.source_id = awbn.source_id\n"
        f"  LEFT JOIN {ALLWISE_PHOTO_TABLE} AS aw "
        "ON awbn.original_ext_source_id = aw.designation\n"
        f"  LEFT JOIN {TMASS_XMATCH_TABLE} AS tmbn ON gs.source_id = tmbn.source_id\n"
        f"  LEFT JOIN {TMASS_PHOTO_TABLE} AS tm "
        "ON tmbn.original_ext_source_id = tm.designation"
    )


def build_quiet_negative_adql(limit: int | None = None) -> str:
    """Construct the ADQL for the pre-registered quiet-negative population.

    Cuts implemented here:
      - WISE-only coverage class (pre-reg §2)
      - Quiet-negative additional criteria (pre-reg §6)

    SIMBAD-based YSO / AGN / debris-disk exclusion is not encoded in ADQL
    because SIMBAD is not a Gaia-archive table. That exclusion is applied
    in a post-query step against an external catalog crossmatch; see
    docstring of ``fetch_quiet_negative_controls``.
    """
    cov = COVERAGE_CLASS_CUTS
    qn = QUIET_NEGATIVE_CUTS

    select_clause = _build_select_clause()
    join_clause = _build_join_clause()

    where_clauses = [
        # Coverage class
        f"gs.parallax_over_error >= {cov['parallax_over_error_min']}",
        f"gs.parallax > 0",
        f"gs.phot_g_mean_mag <= {cov['g_mag_max']}",
        f"1000.0 / gs.parallax <= {cov['distance_pc_max']}",
        f"awbn.angular_distance IS NOT NULL",
        f"awbn.angular_distance <= {qn['allwise_angular_distance_max_arcsec']}",
        # SNR thresholds expressed as magnitude-error upper bounds (Pogson):
        #   snr >= N  <=>  mag_error <= 1.0857 / N
        f"aw.w1mpro_error <= {1.0857 / cov['w1_snr_min']:.6f}",
        f"aw.w2mpro_error <= {1.0857 / cov['w2_snr_min']:.6f}",
        f"aw.w3mpro_error <= {1.0857 / cov['w3_snr_min']:.6f}",
        # Quiet-negative additional cuts
        f"gs.ruwe < {qn['ruwe_max']}",
        f"gs.duplicated_source = 'false'",
        f"gs.non_single_star = 0",
        f"gs.classprob_dsc_combmod_galaxy < {qn['galaxy_prob_max']}",
        f"gs.classprob_dsc_combmod_quasar < {qn['quasar_prob_max']}",
        f"awbn.number_of_neighbours = {int(qn['allwise_n_neighbours'])}",
        f"awbn.number_of_mates = {int(qn['allwise_n_mates'])}",
        f"ABS(gs.b) > {qn['galactic_latitude_min_deg']}",
        f"tmbn.angular_distance IS NOT NULL",
        f"tmbn.angular_distance <= {qn['tmass_angular_distance_max_arcsec']}",
        # AllWISE contamination flags must be clean in W1/W2/W3.
        "(aw.cc_flags IS NULL OR aw.cc_flags = '0000')",
        "(aw.ext_flag IS NULL OR aw.ext_flag = 0)",
    ]

    where_block = "\n  AND ".join(where_clauses)

    query = (
        ("SELECT TOP " + str(int(limit)) if limit else "SELECT")
        + "\n  "
        + select_clause
        + "\n"
        + join_clause
        + "\nWHERE\n  "
        + where_block
    )
    return query


def build_target_adql(source_ids: Iterable[int]) -> str:
    """Construct ADQL fetching the join row for an explicit list of Gaia DR3 IDs.

    Source IDs are validated as positive 64-bit integers before being
    formatted inline. ADQL has no parameterised-query construct, so the
    integer validation is the injection-safety boundary.
    """
    validated = _validate_source_ids(source_ids)
    if not validated:
        raise ValueError("source_ids must contain at least one ID")

    id_list = ", ".join(str(sid) for sid in validated)

    select_clause = _build_select_clause()
    join_clause = _build_join_clause()
    query = (
        "SELECT\n  "
        + select_clause
        + "\n"
        + join_clause
        + f"\nWHERE\n  gs.source_id IN ({id_list})"
    )
    return query


def _validate_source_ids(source_ids: Iterable[int]) -> list[int]:
    out: list[int] = []
    for sid in source_ids:
        if not isinstance(sid, int) or isinstance(sid, bool):
            raise TypeError(f"source_id must be int, got {type(sid).__name__}")
        if sid <= 0:
            raise ValueError(f"source_id must be a positive integer, got {sid}")
        if sid.bit_length() > 64:
            raise ValueError(f"source_id exceeds 64-bit range, got {sid}")
        out.append(sid)
    return out


def _load_cached_result(cache_path: Path, query_hash: str) -> SourceQueryResult | None:
    if not cache_path.exists():
        return None
    sidecar = cache_path.with_suffix(cache_path.suffix + ".meta")
    if not sidecar.exists():
        return None
    cached_hash = sidecar.read_text(encoding="utf-8").strip().splitlines()[0]
    if cached_hash != query_hash:
        return None
    df = pd.read_parquet(cache_path)
    query_text = "\n".join(sidecar.read_text(encoding="utf-8").splitlines()[1:])
    return SourceQueryResult(
        sources=df,
        query_text=query_text,
        query_hash=query_hash,
        n_sources=len(df),
    )


def _save_cached_result(cache_path: Path, result: SourceQueryResult) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    result.sources.to_parquet(cache_path, index=False)
    sidecar = cache_path.with_suffix(cache_path.suffix + ".meta")
    sidecar.write_text(
        result.query_hash + "\n" + result.query_text + "\n",
        encoding="utf-8",
    )


_TAP_MAX_RETRIES = 5
_TAP_RETRY_BACKOFF_SECONDS = (5, 15, 30, 60, 120)


def _resolve_credentials_path() -> Path | None:
    """Return the first usable credentials path or None.

    Honours the PHAROS_GAIA_CREDENTIALS environment variable as an
    override. Otherwise checks the default search path. Files that are
    group- or world-readable are rejected to avoid using a credential
    that may have leaked into a shared workspace.
    """
    override = os.environ.get("PHAROS_GAIA_CREDENTIALS")
    candidates: tuple[Path, ...]
    if override:
        candidates = (Path(override).expanduser(),)
    else:
        candidates = _GAIA_CREDENTIALS_PATHS
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning(
                "ignoring credentials file %s: must be mode 600 (user-only)",
                path,
            )
            continue
        return path
    return None


def _maybe_login() -> None:
    """Attempt Gaia login from a credentials file. No-op on failure.

    Called at most once per process via the ``_login_state`` flag. Errors
    are logged but never raise — the caller is allowed to continue in
    anonymous mode if authentication is unavailable.
    """
    global _login_state
    if _login_state != "unknown":
        return

    path = _resolve_credentials_path()
    if path is None:
        _login_state = "anonymous"
        logger.debug("no Gaia credentials file found; running anonymously")
        return

    try:
        from astroquery.gaia import Gaia  # type: ignore[import-untyped]

        Gaia.login(credentials_file=str(path), verbose=False)
        _login_state = "authenticated"
        logger.info("Gaia authenticated session active")
    except Exception as exc:  # noqa: BLE001 — log only, never expose creds
        _login_state = "anonymous"
        logger.warning(
            "Gaia login failed (%s); falling back to anonymous", type(exc).__name__
        )


def _execute_tap_query(query_text: str) -> pd.DataFrame:
    """Submit ADQL to the Gaia archive and return rows as a DataFrame.

    Imports astroquery lazily so the rest of this module can be imported
    in environments that do not have astroquery installed (e.g., CI for
    pure-logic tests).

    Retries transient connection errors (TLS resets, ECONNRESET, transient
    HTTP errors) with an exponential-style backoff before giving up. The
    Gaia archive is unstable during the DR4 transition.
    """
    import time

    from astroquery.gaia import Gaia  # type: ignore[import-untyped]
    from requests.exceptions import (  # type: ignore[import-untyped]
        ConnectionError as RequestsConnectionError,
    )
    from requests.exceptions import HTTPError as RequestsHTTPError

    transient_errors: tuple[type[BaseException], ...] = (
        ConnectionResetError,
        ConnectionError,
        TimeoutError,
        RequestsConnectionError,
        RequestsHTTPError,
        OSError,
    )

    _maybe_login()
    logger.info(
        "submitting Gaia TAP query (%d chars, session=%s)",
        len(query_text),
        _login_state,
    )
    last_error: BaseException | None = None
    for attempt in range(1, _TAP_MAX_RETRIES + 1):
        try:
            job = Gaia.launch_job_async(query_text, dump_to_file=False)
            table = job.get_results()
            df = table.to_pandas()
            logger.info(
                "query returned %d rows (attempt %d)", len(df), attempt
            )
            return df
        except transient_errors as exc:
            last_error = exc
            if attempt >= _TAP_MAX_RETRIES:
                logger.error(
                    "Gaia TAP query failed after %d attempts: %s",
                    _TAP_MAX_RETRIES,
                    exc,
                )
                raise
            backoff = _TAP_RETRY_BACKOFF_SECONDS[
                min(attempt - 1, len(_TAP_RETRY_BACKOFF_SECONDS) - 1)
            ]
            logger.warning(
                "Gaia TAP transient error on attempt %d (%s); sleeping %ds",
                attempt,
                type(exc).__name__,
                backoff,
            )
            time.sleep(backoff)
    # Unreachable — the loop above either returns or raises.
    raise RuntimeError("unreachable") from last_error


def fetch_quiet_negative_controls(
    cache_path: Path,
    *,
    limit: int | None = 100_000,
    use_cache: bool = True,
) -> SourceQueryResult:
    """Fetch the pre-registered quiet-negative control population.

    The result is cached to ``cache_path`` as parquet, with a sidecar
    ``.parquet.meta`` file containing the SHA-256 of the ADQL text. Any
    change to the pre-registered cuts changes the hash and invalidates
    the cache.

    Note: SIMBAD-based YSO / AGN / debris-disk exclusion (pre-reg §6) is
    not encoded in this query. Apply that filter as a separate post-query
    step against an external catalog crossmatch before the quiet-negative
    population is used for empirical p-value calibration.
    """
    query = build_quiet_negative_adql(limit=limit)
    query_hash = _hash_query(query)

    if use_cache:
        cached = _load_cached_result(cache_path, query_hash)
        if cached is not None:
            logger.info("loaded quiet-negative cache (%d rows)", cached.n_sources)
            return cached

    df = _execute_tap_query(query)
    result = SourceQueryResult(
        sources=df,
        query_text=query,
        query_hash=query_hash,
        n_sources=len(df),
    )
    _save_cached_result(cache_path, result)
    return result


def fetch_targets_by_source_id(
    source_ids: Iterable[int],
    cache_path: Path | None = None,
    *,
    use_cache: bool = True,
) -> SourceQueryResult:
    """Fetch the Gaia + AllWISE + 2MASS join row for an explicit ID list."""
    query = build_target_adql(source_ids)
    query_hash = _hash_query(query)

    if cache_path is not None and use_cache:
        cached = _load_cached_result(cache_path, query_hash)
        if cached is not None:
            logger.info("loaded target cache (%d rows)", cached.n_sources)
            return cached

    df = _execute_tap_query(query)
    result = SourceQueryResult(
        sources=df,
        query_text=query,
        query_hash=query_hash,
        n_sources=len(df),
    )
    if cache_path is not None:
        _save_cached_result(cache_path, result)
    return result

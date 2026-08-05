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
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from pharos import artifacts, validation

logger = logging.getLogger(__name__)

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
    query_traces: tuple["QueryTrace", ...] = ()
    gaia_rows: int = 0


@dataclass(frozen=True)
class QueryTrace:
    """Hash-only provenance for one remote request."""

    service: str
    query_sha256: str
    response_rows: int


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


# ---------------------------------------------------------------------------
# Split-query column sets. The big 5-way JOIN of the quiet-negative query
# overwhelms the Gaia archive planner during the DR4 transition (>90 min
# timeouts), so we split it into three short, indexed queries and merge
# client-side. The Hephaistos target query stays as a single 5-way JOIN
# because WHERE source_id IN (7 IDs) is trivially selective.
# ---------------------------------------------------------------------------

_GAIA_SOURCE_COLUMNS: tuple[str, ...] = (
    "source_id AS gaia_dr3_source_id",
    "ra",
    "dec",
    "l AS galactic_l",
    "b AS galactic_b",
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
    "classprob_dsc_combmod_quasar AS qso_probability",
    "classprob_dsc_combmod_galaxy AS galaxy_probability",
    "teff_gspphot",
    "logg_gspphot",
    "distance_gspphot",
    "ag_gspphot",
)

_ALLWISE_COLUMNS: tuple[str, ...] = (
    "awbn.source_id AS gaia_dr3_source_id",
    "awbn.angular_distance AS wise_xm_angular_distance",
    "awbn.number_of_neighbours AS wise_xm_n_neighbours",
    "awbn.number_of_mates AS wise_xm_n_mates",
    "awbn.xm_flag AS wise_xm_flag",
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
)

_TMASS_COLUMNS: tuple[str, ...] = (
    "tmbn.source_id AS gaia_dr3_source_id",
    "tmbn.angular_distance AS tmass_xm_angular_distance",
    "tm.designation AS tmass_designation",
    "tm.j_m AS tmass_j_m",
    "tm.j_msigcom AS tmass_j_msigcom",
    "tm.h_m AS tmass_h_m",
    "tm.h_msigcom AS tmass_h_msigcom",
    "tm.ks_m AS tmass_ks_m",
    "tm.ks_msigcom AS tmass_ks_msigcom",
)


def build_quiet_negative_gaia_adql(limit: int, *, after_source_id: int = 0) -> str:
    """Step 1 of the split quiet-negative query: gaia_source only.

    Applies all gaia_source-level predicates from the WISE-only coverage
    class (pre-reg §2) and the quiet-negative additional cuts (pre-reg §6)
    that don't require the AllWISE / 2MASS tables. Returns the candidate
    source IDs and their gaia_source columns for downstream JOINs in
    Python rather than ADQL.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > validation.MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError(
            f"limit must be within [1, {validation.MAX_NETWORK_SOURCE_CHUNK}]"
        )
    if not isinstance(after_source_id, int) or isinstance(after_source_id, bool):
        raise TypeError("after_source_id must be an integer")
    if after_source_id < 0 or after_source_id.bit_length() > 64:
        raise ValueError("after_source_id must be an unsigned 64-bit integer")

    cov = COVERAGE_CLASS_CUTS
    qn = QUIET_NEGATIVE_CUTS

    select_clause = ",\n  ".join(_GAIA_SOURCE_COLUMNS)
    where_clauses = [
        f"parallax_over_error >= {cov['parallax_over_error_min']}",
        "parallax > 0",
        f"phot_g_mean_mag <= {cov['g_mag_max']}",
        "phot_bp_rp_excess_factor IS NOT NULL",
        f"parallax >= {1000.0 / cov['distance_pc_max']:.6f}",
        f"ruwe < {qn['ruwe_max']}",
        "duplicated_source = 'false'",
        "non_single_star = 0",
        f"classprob_dsc_combmod_galaxy < {qn['galaxy_prob_max']}",
        f"classprob_dsc_combmod_quasar < {qn['quasar_prob_max']}",
        f"ABS(b) > {qn['galactic_latitude_min_deg']}",
        f"source_id > {after_source_id}",
    ]
    where_block = "\n  AND ".join(where_clauses)
    return (
        f"SELECT TOP {limit}\n  "
        + select_clause
        + f"\nFROM {GAIA_SOURCE_TABLE}\nWHERE\n  "
        + where_block
        + "\nORDER BY source_id"
    )


def build_quiet_negative_joined_adql(limit: int, *, after_source_id: int = 0) -> str:
    """Build one bounded, keyset-paginated Gaia+AllWISE+2MASS page.

    Page size is capped at 500 by the frozen trust-boundary requirement.
    Unlike the historical TOP 50,000 join, a TOP 500 page has been probed
    successfully against the live Gaia TAP service and avoids sending two
    additional per-source-list requests for every sparse Gaia page.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > validation.MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError(
            f"limit must be within [1, {validation.MAX_NETWORK_SOURCE_CHUNK}]"
        )
    if not isinstance(after_source_id, int) or isinstance(after_source_id, bool):
        raise TypeError("after_source_id must be an integer")
    if after_source_id < 0 or after_source_id.bit_length() > 64:
        raise ValueError("after_source_id must be an unsigned 64-bit integer")

    cov = COVERAGE_CLASS_CUTS
    qn = QUIET_NEGATIVE_CUTS
    where_clauses = [
        f"gs.parallax_over_error >= {cov['parallax_over_error_min']}",
        "gs.parallax > 0",
        f"gs.phot_g_mean_mag <= {cov['g_mag_max']}",
        "gs.phot_bp_rp_excess_factor IS NOT NULL",
        f"gs.parallax >= {1000.0 / cov['distance_pc_max']:.6f}",
        f"gs.ruwe < {qn['ruwe_max']}",
        "gs.duplicated_source = 'false'",
        "gs.non_single_star = 0",
        f"gs.classprob_dsc_combmod_galaxy < {qn['galaxy_prob_max']}",
        f"gs.classprob_dsc_combmod_quasar < {qn['quasar_prob_max']}",
        f"ABS(gs.b) > {qn['galactic_latitude_min_deg']}",
        f"awbn.angular_distance <= {qn['allwise_angular_distance_max_arcsec']}",
        f"awbn.number_of_neighbours = {int(qn['allwise_n_neighbours'])}",
        f"awbn.number_of_mates = {int(qn['allwise_n_mates'])}",
        f"aw.w1mpro_error <= {1.0857 / cov['w1_snr_min']:.6f}",
        f"aw.w2mpro_error <= {1.0857 / cov['w2_snr_min']:.6f}",
        f"aw.w3mpro_error <= {1.0857 / cov['w3_snr_min']:.6f}",
        "(aw.cc_flags IS NULL OR aw.cc_flags = '0000')",
        "(aw.ext_flag IS NULL OR aw.ext_flag = 0)",
        f"tmbn.angular_distance <= {qn['tmass_angular_distance_max_arcsec']}",
        "tm.ks_m IS NOT NULL",
        "tm.ks_msigcom IS NOT NULL",
        f"gs.source_id > {after_source_id}",
    ]
    return (
        f"SELECT TOP {limit}\n  "
        + _build_select_clause()
        + "\n"
        + _build_join_clause()
        + "\nWHERE\n  "
        + "\n  AND ".join(where_clauses)
        + "\nORDER BY gs.source_id"
    )


def build_allwise_for_ids_adql(source_ids: Iterable[int]) -> str:
    """Step 2: AllWISE photometry for an explicit source ID list.

    Applies pre-registered crossmatch quality and SNR cuts; only rows
    that pass *all* AllWISE-level constraints from pre-reg §2/§6 are
    returned. Sources that don't pass are simply absent from the
    result (which is what we want — they're not part of the
    quiet-negative population).
    """
    cov = COVERAGE_CLASS_CUTS
    qn = QUIET_NEGATIVE_CUTS

    validated = _validate_source_ids(source_ids)
    if not validated:
        raise ValueError("source_ids must contain at least one ID")
    if len(validated) > validation.MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError("AllWISE request exceeds the registered 500-source network chunk")
    id_list = ", ".join(str(sid) for sid in validated)

    select_clause = ",\n  ".join(_ALLWISE_COLUMNS)
    where_clauses = [
        f"awbn.source_id IN ({id_list})",
        f"awbn.angular_distance <= {qn['allwise_angular_distance_max_arcsec']}",
        f"awbn.number_of_neighbours = {int(qn['allwise_n_neighbours'])}",
        f"awbn.number_of_mates = {int(qn['allwise_n_mates'])}",
        f"aw.w1mpro_error <= {1.0857 / cov['w1_snr_min']:.6f}",
        f"aw.w2mpro_error <= {1.0857 / cov['w2_snr_min']:.6f}",
        f"aw.w3mpro_error <= {1.0857 / cov['w3_snr_min']:.6f}",
        "(aw.cc_flags IS NULL OR aw.cc_flags = '0000')",
        "(aw.ext_flag IS NULL OR aw.ext_flag = 0)",
    ]
    where_block = "\n  AND ".join(where_clauses)
    return (
        "SELECT\n  "
        + select_clause
        + f"\nFROM {ALLWISE_XMATCH_TABLE} AS awbn"
        + f"\n  INNER JOIN {ALLWISE_PHOTO_TABLE} AS aw"
        + " ON awbn.original_ext_source_id = aw.designation"
        + "\nWHERE\n  "
        + where_block
    )


def build_tmass_for_ids_adql(source_ids: Iterable[int]) -> str:
    """Step 3: 2MASS photometry for an explicit source ID list."""
    qn = QUIET_NEGATIVE_CUTS

    validated = _validate_source_ids(source_ids)
    if not validated:
        raise ValueError("source_ids must contain at least one ID")
    if len(validated) > validation.MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError("2MASS request exceeds the registered 500-source network chunk")
    id_list = ", ".join(str(sid) for sid in validated)

    select_clause = ",\n  ".join(_TMASS_COLUMNS)
    where_clauses = [
        f"tmbn.source_id IN ({id_list})",
        f"tmbn.angular_distance <= {qn['tmass_angular_distance_max_arcsec']}",
        "tm.ks_m IS NOT NULL",
        "tm.ks_msigcom IS NOT NULL",
    ]
    where_block = "\n  AND ".join(where_clauses)
    return (
        "SELECT\n  "
        + select_clause
        + f"\nFROM {TMASS_XMATCH_TABLE} AS tmbn"
        + f"\n  INNER JOIN {TMASS_PHOTO_TABLE} AS tm"
        + " ON tmbn.original_ext_source_id = tm.designation"
        + "\nWHERE\n  "
        + where_block
    )


def build_quiet_negative_adql(limit: int | None = None) -> str:
    """[DEPRECATED] Single-query form retained for the unit test.

    Submitting this as a single query to the Gaia archive consistently
    times out during the DR4 transition. The production path uses the
    split-query builders above; this string is no longer submitted to
    the server.
    """
    head = "SELECT TOP " + str(int(limit)) if limit else "SELECT"
    return head + " /* split-query path is used instead — see build_quiet_negative_gaia_adql */"


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
        if len(out) > validation.MAX_CLI_SOURCE_IDS:
            raise ValueError(
                f"source_ids exceeds the {validation.MAX_CLI_SOURCE_IDS}-source CLI bound"
            )
    if len(out) != len(set(out)):
        raise ValueError("duplicate source_ids are forbidden")
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
    sidecar = cache_path.with_suffix(cache_path.suffix + ".meta")
    parquet_fd, parquet_tmp_name = tempfile.mkstemp(
        prefix=f".{cache_path.name}.", suffix=".tmp", dir=cache_path.parent
    )
    os.close(parquet_fd)
    sidecar_fd, sidecar_tmp_name = tempfile.mkstemp(
        prefix=f".{sidecar.name}.", suffix=".tmp", dir=sidecar.parent
    )
    parquet_tmp = Path(parquet_tmp_name)
    sidecar_tmp = Path(sidecar_tmp_name)
    try:
        with os.fdopen(sidecar_fd, "w", encoding="utf-8") as handle:
            handle.write(result.query_hash + "\n" + result.query_text + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        sidecar_fd = -1
        result.sources.to_parquet(parquet_tmp, index=False)
        os.replace(parquet_tmp, cache_path)
        os.replace(sidecar_tmp, sidecar)
    finally:
        if sidecar_fd >= 0:
            os.close(sidecar_fd)
        parquet_tmp.unlink(missing_ok=True)
        sidecar_tmp.unlink(missing_ok=True)


_TAP_MAX_RETRIES = 3
_TAP_RETRY_BACKOFF_SECONDS = (5, 15, 30)
_TAP_POLL_INTERVAL_SECONDS = 10
_TAP_POLL_TIMEOUT_SECONDS = 7200  # 2 hours; Gaia's async job timeout


def _resolve_credentials_path() -> Path | None:
    """Return the first usable credentials path or None.

    Public-catalog queries use anonymous least-privilege access by default.
    Authentication is enabled only by an explicit PHAROS_GAIA_CREDENTIALS
    path.  Repository-local and non-0600 files fail closed.
    """
    override = os.environ.get("PHAROS_GAIA_CREDENTIALS")
    if not override:
        return None
    candidates = (Path(override).expanduser(),)
    repository_root = Path(__file__).resolve().parents[2]
    for path in candidates:
        resolved = path.resolve(strict=False)
        if resolved.is_relative_to(repository_root):
            raise PermissionError("repository-local credential files are forbidden")
        if not path.exists() or not path.is_file():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise PermissionError("Gaia credentials file must have mode 0600")
        return path
    return None


def _maybe_login() -> None:
    """Attempt Gaia login from a credential file, failing closed on rejection.

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
    except Exception as exc:  # noqa: BLE001 — exception type only; never expose creds
        _login_state = "unknown"
        raise RuntimeError(f"Gaia authentication failed ({type(exc).__name__})") from exc

    # Astroquery's Gaia.login() may log an error and return normally on
    # 401 — verify the session actually authenticated by inspecting the
    # internal flag rather than trusting the call's return.
    is_logged_in = getattr(Gaia, "_TapPlus__isLoggedIn", False)
    if is_logged_in:
        _login_state = "authenticated"
        logger.info("Gaia authenticated session active")
    else:
        _login_state = "unknown"
        raise RuntimeError("Gaia authentication failed")


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

    # background=True makes launch_job_async return immediately after
    # the server accepts the submission. Without it, astroquery internally
    # calls wait_for_job_end() which polls in a tight loop — and that
    # polling connection is what's getting reset during the DR4 transition.
    def _submit() -> object:
        return Gaia.launch_job_async(query_text, dump_to_file=False, background=True)

    job = _with_transient_retry(
        _submit,
        transient_errors=transient_errors,
        operation_label="submission",
    )

    job_id = getattr(job, "jobid", None) or getattr(job, "_Job__jobid", None)
    logger.info("Gaia job submitted (job_id=%s); polling phase", job_id)

    # Poll for completion with short-lived HTTP calls. A single
    # ConnectionResetError on a poll doesn't kill the fetch — the next
    # poll uses a fresh connection.
    deadline = time.monotonic() + _TAP_POLL_TIMEOUT_SECONDS
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Gaia job {job_id} did not complete within {_TAP_POLL_TIMEOUT_SECONDS}s"
            )
        try:
            phase = job.get_phase(update=True)
        except transient_errors as exc:
            logger.warning(
                "phase poll transient error (%s); sleeping %ds",
                type(exc).__name__,
                _TAP_POLL_INTERVAL_SECONDS,
            )
            time.sleep(_TAP_POLL_INTERVAL_SECONDS)
            continue
        if phase == "COMPLETED":
            break
        if phase in {"ERROR", "ABORTED"}:
            raise RuntimeError(f"Gaia job {job_id} ended with phase {phase}")
        logger.debug(
            "job %s phase=%s; sleeping %ds",
            job_id,
            phase,
            _TAP_POLL_INTERVAL_SECONDS,
        )
        time.sleep(_TAP_POLL_INTERVAL_SECONDS)

    # Result fetch is another isolated request; retry transient errors.
    def _fetch_results() -> pd.DataFrame:
        table = job.get_results()
        return table.to_pandas()

    df = _with_transient_retry(
        _fetch_results,
        transient_errors=transient_errors,
        operation_label="result-fetch",
    )
    logger.info("query returned %d rows (job_id=%s)", len(df), job_id)
    return df


def _with_transient_retry(
    fn,
    *,
    transient_errors: tuple[type[BaseException], ...],
    operation_label: str,
):
    """Retry ``fn`` on transient HTTP/TLS errors with backoff."""
    import time

    last_error: BaseException | None = None
    for attempt in range(1, _TAP_MAX_RETRIES + 1):
        try:
            return fn()
        except transient_errors as exc:
            last_error = exc
            if attempt >= _TAP_MAX_RETRIES:
                logger.error(
                    "Gaia TAP %s failed after %d attempts: %s",
                    operation_label,
                    _TAP_MAX_RETRIES,
                    exc,
                )
                raise
            backoff = _TAP_RETRY_BACKOFF_SECONDS[
                min(attempt - 1, len(_TAP_RETRY_BACKOFF_SECONDS) - 1)
            ]
            logger.warning(
                "Gaia TAP %s error on attempt %d (%s); sleeping %ds",
                operation_label,
                attempt,
                type(exc).__name__,
                backoff,
            )
            time.sleep(backoff)
    raise RuntimeError(f"Gaia TAP {operation_label} unreachable") from last_error


def fetch_quiet_negative_controls(
    cache_path: Path,
    *,
    limit: int | None = 50_000,
    use_cache: bool = True,
    generating_command: str = "python -m pharos.cli fetch_quiet_negative",
) -> SourceQueryResult:
    """Fetch the raw quiet-negative candidate pool.

    Submitted as bounded, keyset-paginated TOP-500 joined pages.  The
    historical unbounded 5-way join timed out; bounded pages were live-
    probed before adoption and keep each request inside the frozen source
    limit. The legacy sidecar remains insufficient for conformant release
    provenance and cannot pass the artifact loader.

    This fetch is not by itself a conformant quiet-negative population.
    The magnitude-binned BP/RP-excess cut and SIMBAD-based YSO / AGN /
    debris-disk exclusions (pre-reg §6) are not encoded here. Apply and
    provenance those filters before using the result for empirical
    p-value calibration. The v0.1.0 release did not do so; see the release
    conformance record.
    """
    if limit is None or not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be a positive integer")
    if limit < 1 or limit > 250_000:
        raise ValueError("limit must be within [1, 250000]")

    page_size = validation.MAX_NETWORK_SOURCE_CHUNK
    cursor = 0
    gaia_rows = 0
    joined_parts: list[pd.DataFrame] = []
    traces: list[QueryTrace] = []
    query_texts: list[str] = []
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    raw_manifest = artifacts.raw_manifest_path(cache_path)
    if use_cache and (cache_path.exists() or raw_manifest.exists()):
        try:
            cached, checkpoint = artifacts.load_raw_checkpoint(cache_path)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise RuntimeError("refusing legacy, incomplete, or invalid raw cache") from exc
        joined_parts.append(cached)
        cursor = int(checkpoint["cursor_source_id"])
        gaia_rows = int(checkpoint["gaia_rows"])
        traces = [
            QueryTrace(
                str(trace["service"]),
                str(trace["query_sha256"]),
                int(trace["response_rows"]),
            )
            for trace in checkpoint["query_traces"]
        ]
        retrieved_at = str(checkpoint["retrieved_at_utc"])
        logger.info("resuming validated raw checkpoint at %d joined rows", len(cached))

    while sum(len(part) for part in joined_parts) < limit:
        joined_query = build_quiet_negative_joined_adql(page_size, after_source_id=cursor)
        page = _execute_tap_query(joined_query)
        validation.validate_exact_columns(
            page, validation.JOINED_SOURCE_COLUMNS, context="joined candidate page"
        )
        gaia_view = page.loc[:, validation.GAIA_RESPONSE_COLUMNS]
        validation.validate_gaia_response(gaia_view, requested_rows=page_size)
        requested_ids = set(gaia_view["gaia_dr3_source_id"].astype(int))
        validation.validate_allwise_response(
            page.loc[:, validation.ALLWISE_RESPONSE_COLUMNS], requested_ids=requested_ids
        )
        validation.validate_tmass_response(
            page.loc[:, validation.TMASS_RESPONSE_COLUMNS], requested_ids=requested_ids
        )
        query_texts.append(joined_query)
        traces.append(
            QueryTrace("Gaia TAP joined", _hash_query(joined_query), len(page))
        )
        if page.empty:
            raise RuntimeError(
                f"Gaia candidates exhausted before {limit} joined rows were collected"
            )
        next_cursor = int(page["gaia_dr3_source_id"].max())
        if next_cursor <= cursor:
            raise RuntimeError("Gaia keyset pagination did not advance")
        cursor = next_cursor
        gaia_rows += len(page)
        joined_parts.append(page)
        logger.info(
            "quiet-negative candidate progress: %d/%d joined rows (%d Gaia rows)",
            sum(len(part) for part in joined_parts),
            limit,
            gaia_rows,
        )
        checkpoint_frame = pd.concat(joined_parts, ignore_index=True)
        artifacts.write_raw_checkpoint(
            cache_path=cache_path,
            frame=checkpoint_frame,
            query_traces=[
                {
                    "service": trace.service,
                    "query_sha256": trace.query_sha256,
                    "response_rows": trace.response_rows,
                }
                for trace in traces
            ],
            gaia_rows=gaia_rows,
            retrieved_at_utc=retrieved_at,
            generating_command=generating_command,
        )

    merged = pd.concat(joined_parts, ignore_index=True)
    if merged["gaia_dr3_source_id"].duplicated().any():
        raise RuntimeError("duplicate source identifier appeared across Gaia pages")
    combined_text = "\n-- NEXT REQUEST --\n".join(query_texts)
    combined_hash = artifacts.sha256_strings([trace.query_sha256 for trace in traces])
    result = SourceQueryResult(
        sources=merged,
        query_text=combined_text,
        query_hash=combined_hash,
        n_sources=len(merged),
        query_traces=tuple(traces),
        gaia_rows=gaia_rows,
    )
    return result


# Maximum source IDs per IN-list query. Empirically the Gaia archive
# rejects single ADQL queries with ~100K+ characters during the DR4
# transition; 500 IDs is a comfortable margin (~10K char query).
_TARGET_QUERY_CHUNK_SIZE: int = 500


def _build_gaia_by_ids_adql(ids: list[int]) -> str:
    """SELECT from gaia_source WHERE source_id IN (...). Single-table, no joins."""
    select_clause = ",\n  ".join(_GAIA_SOURCE_COLUMNS)
    id_str = ", ".join(str(sid) for sid in ids)
    return (
        "SELECT\n  " + select_clause + f"\nFROM {GAIA_SOURCE_TABLE}\nWHERE source_id IN ({id_str})"
    )


def _build_allwise_by_ids_unfiltered(ids: list[int]) -> str:
    """AllWISE join for explicit IDs, no SNR/coverage cuts applied."""
    select_clause = ",\n  ".join(_ALLWISE_COLUMNS)
    id_str = ", ".join(str(sid) for sid in ids)
    return (
        "SELECT\n  "
        + select_clause
        + f"\nFROM {ALLWISE_XMATCH_TABLE} AS awbn"
        + f"\n  INNER JOIN {ALLWISE_PHOTO_TABLE} AS aw"
        + " ON awbn.original_ext_source_id = aw.designation"
        + f"\nWHERE awbn.source_id IN ({id_str})"
    )


def _build_tmass_by_ids_unfiltered(ids: list[int]) -> str:
    """2MASS join for explicit IDs, no angular-distance cut applied."""
    select_clause = ",\n  ".join(_TMASS_COLUMNS)
    id_str = ", ".join(str(sid) for sid in ids)
    return (
        "SELECT\n  "
        + select_clause
        + f"\nFROM {TMASS_XMATCH_TABLE} AS tmbn"
        + f"\n  INNER JOIN {TMASS_PHOTO_TABLE} AS tm"
        + " ON tmbn.original_ext_source_id = tm.designation"
        + f"\nWHERE tmbn.source_id IN ({id_str})"
    )


def fetch_targets_by_source_id(
    source_ids: Iterable[int],
    cache_path: Path | None = None,
    *,
    use_cache: bool = True,
) -> SourceQueryResult:
    """Fetch the Gaia + AllWISE + 2MASS join row for an explicit ID list.

    Submitted as three small per-table queries (gaia_source, AllWISE
    join, 2MASS join) and merged client-side. The 5-way JOIN form is
    consistently failing on the Gaia archive during the DR4 transition.
    Long ID lists are chunked into batches of ``_TARGET_QUERY_CHUNK_SIZE``
    per query.

    Uses LEFT joins via client-side pandas merge so rows missing
    AllWISE or 2MASS data are still preserved (matches the
    pre-v0.1.1 behavior of the single 5-way LEFT JOIN).
    """
    id_list = _validate_source_ids(source_ids)
    if not id_list:
        raise ValueError("source_ids must contain at least one ID")

    full_query_text = build_target_adql(id_list)
    query_hash = _hash_query(full_query_text)

    if cache_path is not None and use_cache:
        cached = _load_cached_result(cache_path, query_hash)
        if cached is not None:
            logger.info("loaded target cache (%d rows)", cached.n_sources)
            return cached

    chunk_size = _TARGET_QUERY_CHUNK_SIZE
    chunks = [id_list[i : i + chunk_size] for i in range(0, len(id_list), chunk_size)]
    n_chunks = len(chunks)
    logger.info(
        "fetching %d targets via 3-step split (gaia + allwise + 2mass), %d chunks each",
        len(id_list),
        n_chunks,
    )

    gaia_parts: list[pd.DataFrame] = []
    allwise_parts: list[pd.DataFrame] = []
    tmass_parts: list[pd.DataFrame] = []
    for i, chunk_ids in enumerate(chunks, 1):
        logger.info("gaia step chunk %d/%d (%d IDs)", i, n_chunks, len(chunk_ids))
        gaia_parts.append(_execute_tap_query(_build_gaia_by_ids_adql(chunk_ids)))
        logger.info("allwise step chunk %d/%d", i, n_chunks)
        allwise_parts.append(_execute_tap_query(_build_allwise_by_ids_unfiltered(chunk_ids)))
        logger.info("tmass step chunk %d/%d", i, n_chunks)
        tmass_parts.append(_execute_tap_query(_build_tmass_by_ids_unfiltered(chunk_ids)))

    gaia_df = pd.concat(gaia_parts, ignore_index=True) if gaia_parts else pd.DataFrame()
    allwise_df = pd.concat(allwise_parts, ignore_index=True) if allwise_parts else pd.DataFrame()
    tmass_df = pd.concat(tmass_parts, ignore_index=True) if tmass_parts else pd.DataFrame()

    df = gaia_df.merge(allwise_df, on="gaia_dr3_source_id", how="left").merge(
        tmass_df, on="gaia_dr3_source_id", how="left"
    )
    logger.info(
        "merged: %d gaia × %d allwise × %d 2mass -> %d joined rows",
        len(gaia_df),
        len(allwise_df),
        len(tmass_df),
        len(df),
    )

    result = SourceQueryResult(
        sources=df,
        query_text=full_query_text,
        query_hash=query_hash,
        n_sources=len(df),
    )
    if cache_path is not None:
        _save_cached_result(cache_path, result)
    return result

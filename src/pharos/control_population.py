"""Reproduce the failed v0.1.2 quiet-negative control pilot.

The reproduction path is operationally quarantined: it can write only to the
ignored failed-attempt locations, emits a failed/non-authorizing manifest, and
cannot publish a release accepted by scientific analysis.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pharos import artifacts, sources, validation

logger = logging.getLogger(__name__)

BP_RP_G_MAG_BIN_WIDTH = validation.BP_RP_G_MAG_BIN_WIDTH
BP_RP_EXCESS_MAX_DELTA = validation.BP_RP_EXCESS_MAX_DELTA
EXCLUSION_RADIUS_ARCSEC = 30.0
SIMBAD_SOURCE_CHUNK = validation.MAX_NETWORK_SOURCE_CHUNK
SIMBAD_MAXREC = SIMBAD_SOURCE_CHUNK * validation.MAX_MATCHES_PER_SOURCE_CATALOG + 1
CHEN_CATALOG = "J/ApJS/211/25/catalog"
CHEN_RELEASE = validation.CHEN_EXCLUSION_RELEASE
FAILED_V012_OUTPUT_RELATIVE = Path("controls/quiet_negative_v0.1.2_hardened")
FAILED_V012_RAW_CACHE_RELATIVE = Path(
    "controls/cache/quiet_negative_v0.1.2_hardened.raw.parquet"
)
FAILED_PILOT_SCHEMA_VERSION = "pharos.quiet-negative-failed-pilot.v1"

# Fixed SIMBAD object-type vocabulary for the frozen YSO/AGN exclusions.
# The query uses the full ``otypes`` relation rather than only basic.otype,
# so secondary classifications are included as well.
SIMBAD_YSO_TYPES = validation.SIMBAD_YSO_TYPES
SIMBAD_AGN_TYPES = validation.SIMBAD_AGN_TYPES


@dataclass(frozen=True)
class RemoteTrace:
    service: str
    endpoint: str
    query_sha256: str
    input_sha256: str
    response_sha256: str
    response_rows: int
    requested_at_utc: str
    received_at_utc: str


@dataclass(frozen=True)
class ControlBuildResult:
    controls: pd.DataFrame
    exclusions: pd.DataFrame
    manifest: dict[str, Any]
    manifest_path: Path


def apply_bp_rp_excess_cut(candidates: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen ±0.1 magnitude-binned BP/RP excess-factor cut."""
    return validation.derive_bp_rp_controls(candidates)


def _simbad_query_text() -> str:
    types = sorted(SIMBAD_YSO_TYPES | SIMBAD_AGN_TYPES)
    type_list = ", ".join(f"'{otype}'" for otype in types)
    radius_degrees = EXCLUSION_RADIUS_ARCSEC / 3600.0
    return (
        "SELECT t.gaia_dr3_source_id AS gaia_dr3_source_id, "
        "b.main_id AS matched_object_id, o.otype AS matched_otype, "
        "DISTANCE(POINT('ICRS', t.ra, t.dec), POINT('ICRS', b.ra, b.dec)) * 3600.0 "
        "AS angular_distance_arcsec "
        "FROM TAP_UPLOAD.targets AS t "
        "JOIN basic AS b ON 1 = CONTAINS(POINT('ICRS', b.ra, b.dec), "
        f"CIRCLE('ICRS', t.ra, t.dec, {radius_degrees:.12f})) "
        "JOIN otypes AS o ON b.oid = o.oidref "
        f"WHERE o.otype IN ({type_list}) "
        "ORDER BY gaia_dr3_source_id, angular_distance_arcsec"
    )


def _validate_simbad_response(frame: pd.DataFrame, requested_ids: set[int]) -> None:
    validation.validate_exact_columns(
        frame, validation.SIMBAD_RESPONSE_COLUMNS, context="SIMBAD response"
    )
    if len(frame) >= SIMBAD_MAXREC:
        raise ValueError("SIMBAD response reached maxrec and may be truncated")
    if frame.empty:
        return
    if not pd.api.types.is_integer_dtype(frame["gaia_dr3_source_id"].dtype):
        raise TypeError("SIMBAD response source identifiers must be integers")
    if not set(frame["gaia_dr3_source_id"].astype(int)).issubset(requested_ids):
        raise ValueError("SIMBAD returned an unrequested source identifier")
    distances = frame["angular_distance_arcsec"]
    if not pd.api.types.is_numeric_dtype(distances.dtype):
        raise TypeError("SIMBAD angular distances must be numeric")
    if not np.isfinite(distances.to_numpy(dtype=float)).all():
        raise ValueError("SIMBAD angular distances must be finite")
    if ((distances < 0.0) | (distances > EXCLUSION_RADIUS_ARCSEC)).any():
        raise ValueError("SIMBAD angular distance is outside the registered radius")
    if not frame["matched_otype"].astype(str).isin(SIMBAD_YSO_TYPES | SIMBAD_AGN_TYPES).all():
        raise ValueError("SIMBAD returned an unregistered object type")
    counts = frame.groupby("gaia_dr3_source_id").size()
    if (counts > validation.MAX_MATCHES_PER_SOURCE_CATALOG).any():
        raise ValueError("SIMBAD retained-match bound exceeded")


def fetch_simbad_exclusions(candidates: pd.DataFrame) -> tuple[pd.DataFrame, list[RemoteTrace]]:
    """Query YSO/AGN classifications in bounded TAP-upload chunks."""
    from astropy.table import Table  # type: ignore[import-untyped]
    from astroquery.simbad import Simbad  # type: ignore[import-untyped]

    required = ("gaia_dr3_source_id", "ra", "dec")
    if any(column not in candidates.columns for column in required):
        raise ValueError("SIMBAD candidates are missing source ID or coordinates")
    query = _simbad_query_text()
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    parts: list[pd.DataFrame] = []
    traces: list[RemoteTrace] = []
    cumulative_response_rows = 0

    for start in range(0, len(candidates), SIMBAD_SOURCE_CHUNK):
        chunk = candidates.iloc[start : start + SIMBAD_SOURCE_CHUNK]
        ids = chunk["gaia_dr3_source_id"].astype("int64")
        requested_ids = set(ids.astype(int))
        upload = Table(
            {
                "gaia_dr3_source_id": ids.to_numpy(),
                "ra": chunk["ra"].to_numpy(dtype=float),
                "dec": chunk["dec"].to_numpy(dtype=float),
            }
        )
        input_frame = chunk.loc[:, list(required)].copy()
        input_hash = artifacts.sha256_frame(input_frame)
        requested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        table = Simbad.query_tap(
            query,
            maxrec=SIMBAD_MAXREC,
            async_job=True,
            targets=upload,
        )
        if table is None:
            raise RuntimeError("SIMBAD returned no table")
        frame = table.to_pandas()
        received_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        _validate_simbad_response(frame, requested_ids)
        cumulative_response_rows += len(frame)
        if cumulative_response_rows > validation.MAX_EXCLUSION_ROWS:
            raise ValueError("cumulative SIMBAD response exceeds the materialization bound")
        parts.append(frame)
        traces.append(
            RemoteTrace(
                "SIMBAD",
                artifacts.SIMBAD_ENDPOINT,
                query_hash,
                input_hash,
                artifacts.sha256_frame(frame),
                len(frame),
                requested_at,
                received_at,
            )
        )

    raw = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=validation.SIMBAD_RESPONSE_COLUMNS)
    )
    if raw.empty:
        return pd.DataFrame(columns=validation.EXCLUSION_COLUMNS), traces
    out = raw.copy()
    out.insert(1, "exclusion_catalog", "SIMBAD")
    out.insert(
        2,
        "exclusion_class",
        np.where(out["matched_otype"].isin(SIMBAD_YSO_TYPES), "YSO", "AGN"),
    )
    out["catalog_release"] = validation.SIMBAD_EXCLUSION_RELEASE
    out = out.loc[:, validation.EXCLUSION_COLUMNS]
    # SIMBAD can return byte-identical rows from its relation joins.  The
    # remote response has already passed its stricter schema/domain and
    # per-request materialization bounds above.  Normalize only after mapping
    # to the frozen exclusion schema so provenance continues to record the
    # unmodified response row count and digest.
    return normalize_exclusions(out), traces


def _validate_chen_catalog(frame: pd.DataFrame) -> None:
    validation.validate_exact_columns(
        frame, validation.CHEN_RESPONSE_COLUMNS, context="Chen catalog"
    )
    if len(frame) >= validation.MAX_CLI_SOURCE_IDS:
        raise ValueError("Chen catalog reached the registered 10000-row input bound")
    for column in ("_RA", "_DE"):
        if not pd.api.types.is_numeric_dtype(frame[column].dtype):
            raise TypeError(f"Chen catalog {column} must be numeric")
        if not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError(f"Chen catalog {column} must be finite")
    if ((frame["_RA"] < 0.0) | (frame["_RA"] >= 360.0)).any():
        raise ValueError("Chen catalog RA is outside [0, 360)")
    if ((frame["_DE"] < -90.0) | (frame["_DE"] > 90.0)).any():
        raise ValueError("Chen catalog Dec is outside [-90, 90]")
    if frame["Name"].isna().any() or (frame["Name"].astype(str).str.len() == 0).any():
        raise ValueError("Chen catalog object identifiers must be non-empty")


def fetch_chen_exclusions(candidates: pd.DataFrame) -> tuple[pd.DataFrame, list[RemoteTrace]]:
    """Download the fixed Chen catalog and locally match within 30 arcsec."""
    from astropy import units as u  # type: ignore[import-untyped]
    from astropy.coordinates import SkyCoord, search_around_sky  # type: ignore[import-untyped]
    from astroquery.vizier import Vizier  # type: ignore[import-untyped]

    query_descriptor = f"Vizier:{CHEN_CATALOG}:columns=Name,_RA,_DE:row_limit=10000"
    query_hash = hashlib.sha256(query_descriptor.encode("utf-8")).hexdigest()
    client = Vizier(
        columns=list(validation.CHEN_RESPONSE_COLUMNS),
        row_limit=validation.MAX_CLI_SOURCE_IDS,
        timeout=600,
    )
    requested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    tables = client.get_catalogs(CHEN_CATALOG)
    received_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if tables is None or len(tables) != 1:
        raise RuntimeError("Chen catalog query did not return exactly one table")
    catalog = tables[0].to_pandas()
    _validate_chen_catalog(catalog)
    trace = RemoteTrace(
        "VizieR Chen2014",
        artifacts.VIZIER_ENDPOINT,
        query_hash,
        query_hash,
        artifacts.sha256_frame(catalog),
        len(catalog),
        requested_at,
        received_at,
    )
    if catalog.empty or candidates.empty:
        return pd.DataFrame(columns=validation.EXCLUSION_COLUMNS), [trace]

    candidate_coords = SkyCoord(
        candidates["ra"].to_numpy(dtype=float) * u.deg,
        candidates["dec"].to_numpy(dtype=float) * u.deg,
        frame="icrs",
    )
    chen_coords = SkyCoord(
        catalog["_RA"].to_numpy(dtype=float) * u.deg,
        catalog["_DE"].to_numpy(dtype=float) * u.deg,
        frame="icrs",
    )
    candidate_idx, chen_idx, separations, _ = search_around_sky(
        candidate_coords, chen_coords, EXCLUSION_RADIUS_ARCSEC * u.arcsec
    )
    records: list[dict[str, Any]] = []
    for source_index, catalog_index, separation in zip(
        candidate_idx, chen_idx, separations, strict=True
    ):
        records.append(
            {
                "gaia_dr3_source_id": int(candidates.iloc[int(source_index)]["gaia_dr3_source_id"]),
                "exclusion_catalog": "Chen2014",
                "exclusion_class": "debris_disk",
                "matched_object_id": str(catalog.iloc[int(catalog_index)]["Name"]),
                "matched_otype": "debris_disk",
                "angular_distance_arcsec": float(separation.arcsec),
                "catalog_release": CHEN_RELEASE,
            }
        )
    out = pd.DataFrame(records, columns=validation.EXCLUSION_COLUMNS)
    validation.validate_exclusions(out)
    return out, [trace]


def apply_external_exclusions(
    candidates: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> pd.DataFrame:
    validation.validate_exclusions(exclusions)
    excluded_ids = set(exclusions["gaia_dr3_source_id"].astype(int))
    out = candidates[~candidates["gaia_dr3_source_id"].astype(int).isin(excluded_ids)].copy()
    out.reset_index(drop=True, inplace=True)
    return out


def normalize_exclusions(exclusions: pd.DataFrame) -> pd.DataFrame:
    """Remove exact full-tuple duplicates and return a deterministic artifact.

    Distinct SIMBAD object-type classifications for one matched object are
    retained as separate catalog evidence. Conflicting rows for the same
    source/catalog/object/type identity are rejected by ``validate_exclusions``
    rather than silently normalized.
    """
    validation.validate_exact_columns(
        exclusions, validation.EXCLUSION_COLUMNS, context="unnormalized external exclusions"
    )
    if len(exclusions) > validation.MAX_EXCLUSION_ROWS:
        raise ValueError("unnormalized external exclusions exceed the materialization bound")
    normalized = exclusions.drop_duplicates(
        subset=list(validation.EXCLUSION_COLUMNS), ignore_index=True
    )
    normalized = normalized.sort_values(
        list(validation.EXCLUSION_COLUMNS), kind="mergesort", ignore_index=True
    )
    validation.validate_exclusions(normalized)
    return normalized


def reproduce_failed_v012_pilot(
    *,
    output_dir: Path,
    raw_cache_path: Path,
    minimum_joined_rows: int,
    generating_command: str,
    use_raw_cache: bool = True,
) -> ControlBuildResult:
    """Reproduce the failed pilot into fixed ignored quarantine paths only."""
    # Fail before any remote call when the release producer cannot be bound to
    # a clean tracked source/config/lock state.  Manifest construction repeats
    # this check immediately before publication to catch mid-run changes.
    artifacts.software_provenance()
    output_dir = artifacts.validate_repository_path(output_dir, label="output_dir")
    raw_cache_path = artifacts.validate_repository_path(raw_cache_path, label="raw_cache_path")
    repository = artifacts.repository_root()
    required_output = (repository / FAILED_V012_OUTPUT_RELATIVE).resolve()
    required_cache = (repository / FAILED_V012_RAW_CACHE_RELATIVE).resolve()
    if output_dir != required_output or raw_cache_path != required_cache:
        raise ValueError("failed v0.1.2 reproduction may write only to quarantine paths")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("refusing to reuse or overwrite an existing release directory")
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw_result = sources.fetch_quiet_negative_controls(
        raw_cache_path,
        limit=minimum_joined_rows,
        use_cache=use_raw_cache,
        generating_command=generating_command,
    )
    if raw_result.raw_input_provenance is None:
        raise RuntimeError("quiet-negative raw input provenance is missing")
    bp_rp = apply_bp_rp_excess_cut(raw_result.sources)
    simbad, simbad_traces = fetch_simbad_exclusions(bp_rp)
    chen, chen_traces = fetch_chen_exclusions(bp_rp)
    exclusions = pd.concat([simbad, chen], ignore_index=True).loc[:, validation.EXCLUSION_COLUMNS]
    exclusions = normalize_exclusions(exclusions)
    controls = apply_external_exclusions(bp_rp, exclusions)
    validation.validate_control_artifact(controls, minimum_rows=artifacts.MIN_CONTROL_ROWS)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))

    source_traces = [
        RemoteTrace(
            trace.service,
            trace.endpoint,
            trace.query_sha256,
            trace.input_sha256,
            trace.response_sha256,
            trace.response_rows,
            trace.requested_at_utc,
            trace.received_at_utc,
        )
        for trace in raw_result.query_traces
    ]
    query_provenance = [
        {
            "service": trace.service,
            "endpoint": trace.endpoint,
            "query_sha256": trace.query_sha256,
            "input_sha256": trace.input_sha256,
            "response_sha256": trace.response_sha256,
            "response_rows": trace.response_rows,
            "requested_at_utc": trace.requested_at_utc,
            "received_at_utc": trace.received_at_utc,
        }
        for trace in source_traces + simbad_traces + chen_traces
    ]
    simbad_excluded = int(
        exclusions.loc[exclusions["exclusion_catalog"] == "SIMBAD", "gaia_dr3_source_id"].nunique()
    )
    chen_excluded = int(
        exclusions.loc[
            exclusions["exclusion_catalog"] == "Chen2014", "gaia_dr3_source_id"
        ].nunique()
    )
    try:
        raw_candidates_path = artifacts.write_content_addressed_parquet(
            raw_result.sources, directory=staging, prefix="raw_candidates"
        )
        controls_path = artifacts.write_content_addressed_parquet(
            controls, directory=staging, prefix="quiet_negative"
        )
        exclusions_path = artifacts.write_content_addressed_parquet(
            exclusions, directory=staging, prefix="exclusions"
        )
        manifest_path = staging / "manifest.yaml"
        candidate_manifest = artifacts.build_control_manifest(
            raw_candidates_path=raw_candidates_path,
            raw_candidates=raw_result.sources,
            control_path=controls_path,
            controls=controls,
            exclusions_path=exclusions_path,
            exclusions=exclusions,
            retrieved_at_utc=retrieved_at,
            generating_command=generating_command,
            query_provenance=query_provenance,
            filter_counts={
                "gaia_rows": raw_result.gaia_rows,
                "joined_rows": len(raw_result.sources),
                "after_bp_rp_rows": len(bp_rp),
                "simbad_excluded_sources": simbad_excluded,
                "chen_excluded_sources": chen_excluded,
                "excluded_unique_sources": int(exclusions["gaia_dr3_source_id"].nunique()),
                "final_rows": len(controls),
            },
            selection_target_rows=raw_result.selection_target_rows,
            selection_strata=[dict(item) for item in raw_result.selection_strata],
            raw_input_provenance=dict(raw_result.raw_input_provenance),
        )
        manifest = {
            **candidate_manifest,
            "schema_version": FAILED_PILOT_SCHEMA_VERSION,
            "status": "failed",
            "authorization": "non_authorizing",
            "failure_reason": (
                "scientifically material population-selection rules were not "
                "prospectively registered"
            ),
        }
        artifacts.write_exclusive_yaml(manifest, manifest_path)
        artifacts.install_release_directory_no_replace(staging, output_dir)
        final_manifest = output_dir / "manifest.yaml"
        return ControlBuildResult(controls, exclusions, manifest, final_manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

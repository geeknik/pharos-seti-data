"""Build the conformant v0.1.2 quiet-negative control population.

This module stops at the approved boundary: it creates and validates the
control fixture, but does not fit any confounder model.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pharos import artifacts, sources, validation

logger = logging.getLogger(__name__)

BP_RP_G_MAG_BIN_WIDTH = 0.5
BP_RP_EXCESS_MAX_DELTA = 0.1
EXCLUSION_RADIUS_ARCSEC = 30.0
SIMBAD_SOURCE_CHUNK = validation.MAX_NETWORK_SOURCE_CHUNK
SIMBAD_MAXREC = SIMBAD_SOURCE_CHUNK * validation.MAX_MATCHES_PER_SOURCE_CATALOG + 1
CHEN_CATALOG = "J/ApJS/211/25/catalog"
CHEN_RELEASE = "VizieR J/ApJS/211/25/catalog; 2021-08-10 release"

# Fixed SIMBAD object-type vocabulary for the frozen YSO/AGN exclusions.
# The query uses the full ``otypes`` relation rather than only basic.otype,
# so secondary classifications are included as well.
SIMBAD_YSO_TYPES: frozenset[str] = frozenset({"Y*O", "Or*", "TT*", "Ae*", "HH", "out"})
SIMBAD_AGN_TYPES: frozenset[str] = frozenset(
    {"AGN", "SyG", "Sy1", "Sy2", "rG", "LIN", "QSO", "Bla", "BLL"}
)


@dataclass(frozen=True)
class RemoteTrace:
    service: str
    query_sha256: str
    response_rows: int


@dataclass(frozen=True)
class ControlBuildResult:
    controls: pd.DataFrame
    exclusions: pd.DataFrame
    manifest: dict[str, Any]
    manifest_path: Path


def apply_bp_rp_excess_cut(candidates: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen ±0.1 magnitude-binned BP/RP excess-factor cut."""
    validation.validate_exact_columns(
        candidates, validation.JOINED_SOURCE_COLUMNS, context="joined quiet-negative candidates"
    )
    if candidates["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("joined candidates contain duplicate source identifiers")
    required = candidates[["phot_g_mean_mag", "phot_bp_rp_excess_factor"]]
    values = required.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("BP/RP cut inputs must be finite")

    out = candidates.copy()
    out["gmag_bin_lower"] = (
        np.floor(out["phot_g_mean_mag"] / BP_RP_G_MAG_BIN_WIDTH) * BP_RP_G_MAG_BIN_WIDTH
    )
    out["bp_rp_excess_bin_median"] = out.groupby(
        "gmag_bin_lower", observed=True
    )["phot_bp_rp_excess_factor"].transform("median")
    out["bp_rp_excess_delta"] = (
        out["phot_bp_rp_excess_factor"] - out["bp_rp_excess_bin_median"]
    )
    out = out[out["bp_rp_excess_delta"].abs() <= BP_RP_EXCESS_MAX_DELTA].copy()
    out.reset_index(drop=True, inplace=True)
    validation.validate_exact_columns(
        out, validation.CONTROL_ARTIFACT_COLUMNS, context="BP/RP-filtered candidates"
    )
    return out


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
        table = Simbad.query_tap(
            query,
            maxrec=SIMBAD_MAXREC,
            async_job=True,
            targets=upload,
        )
        if table is None:
            raise RuntimeError("SIMBAD returned no table")
        frame = table.to_pandas()
        _validate_simbad_response(frame, requested_ids)
        parts.append(frame)
        traces.append(RemoteTrace("SIMBAD", query_hash, len(frame)))

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
    out["catalog_release"] = "SIMBAD live database"
    out = out.loc[:, validation.EXCLUSION_COLUMNS]
    validation.validate_exclusions(out)
    return out, traces


def _validate_chen_catalog(frame: pd.DataFrame) -> None:
    validation.validate_exact_columns(frame, validation.CHEN_RESPONSE_COLUMNS, context="Chen catalog")
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
    tables = client.get_catalogs(CHEN_CATALOG)
    if tables is None or len(tables) != 1:
        raise RuntimeError("Chen catalog query did not return exactly one table")
    catalog = tables[0].to_pandas()
    _validate_chen_catalog(catalog)
    trace = RemoteTrace("VizieR Chen2014", query_hash, len(catalog))
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
                "gaia_dr3_source_id": int(
                    candidates.iloc[int(source_index)]["gaia_dr3_source_id"]
                ),
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


def _aggregate_traces(traces: list[RemoteTrace]) -> list[dict[str, Any]]:
    services: dict[str, list[RemoteTrace]] = {}
    for trace in traces:
        services.setdefault(trace.service, []).append(trace)
    return [
        {
            "service": service,
            "request_count": len(service_traces),
            "query_sha256": artifacts.sha256_strings(
                [trace.query_sha256 for trace in service_traces]
            ),
            "response_rows": sum(trace.response_rows for trace in service_traces),
        }
        for service, service_traces in sorted(services.items())
    ]


def build_quiet_negative_v012(
    *,
    output_dir: Path,
    raw_cache_path: Path,
    minimum_joined_rows: int,
    generating_command: str,
    use_raw_cache: bool = True,
) -> ControlBuildResult:
    """Build, filter, atomically publish, and reload-validate the fixture."""
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw_result = sources.fetch_quiet_negative_controls(
        raw_cache_path,
        limit=minimum_joined_rows,
        use_cache=use_raw_cache,
        generating_command=generating_command,
    )
    bp_rp = apply_bp_rp_excess_cut(raw_result.sources)
    simbad, simbad_traces = fetch_simbad_exclusions(bp_rp)
    chen, chen_traces = fetch_chen_exclusions(bp_rp)
    exclusions = pd.concat([simbad, chen], ignore_index=True)
    exclusions = exclusions.loc[:, validation.EXCLUSION_COLUMNS]
    validation.validate_exclusions(exclusions)
    controls = apply_external_exclusions(bp_rp, exclusions)
    validation.validate_control_artifact(controls, minimum_rows=artifacts.MIN_CONTROL_ROWS)

    output_dir.mkdir(parents=True, exist_ok=True)
    generation = hashlib.sha256(
        pd.util.hash_pandas_object(
            controls["gaia_dr3_source_id"], index=False
        ).values.tobytes()
    ).hexdigest()[:12]
    controls_path = output_dir / f"quiet_negative.{generation}.parquet"
    exclusions_path = output_dir / f"exclusions.{generation}.parquet"
    manifest_path = output_dir / "manifest.yaml"
    artifacts.atomic_write_parquet(controls, controls_path)
    artifacts.atomic_write_parquet(exclusions, exclusions_path)

    source_traces = [
        RemoteTrace(trace.service, trace.query_sha256, trace.response_rows)
        for trace in raw_result.query_traces
    ]
    query_provenance = _aggregate_traces(source_traces + simbad_traces + chen_traces)
    simbad_excluded = int(
        exclusions.loc[
            exclusions["exclusion_catalog"] == "SIMBAD", "gaia_dr3_source_id"
        ].nunique()
    )
    chen_excluded = int(
        exclusions.loc[
            exclusions["exclusion_catalog"] == "Chen2014", "gaia_dr3_source_id"
        ].nunique()
    )
    manifest = artifacts.build_control_manifest(
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
            "final_rows": len(controls),
        },
    )
    artifacts.validate_control_manifest(manifest)
    artifacts.atomic_write_yaml(manifest, manifest_path)
    reloaded = artifacts.load_control_artifact(manifest_path)
    if not reloaded["gaia_dr3_source_id"].equals(controls["gaia_dr3_source_id"]):
        raise RuntimeError("post-write artifact validation changed source identity/order")
    return ControlBuildResult(controls, exclusions, manifest, manifest_path)

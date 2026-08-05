"""Atomic, versioned artifacts for the v0.1.2 control population."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from pharos import validation

CONTROL_SCHEMA_VERSION = "pharos.quiet-negative.v0.1.2"
MANIFEST_SCHEMA_VERSION = "pharos.quiet-negative-manifest.v1"
RAW_SCHEMA_VERSION = "pharos.quiet-negative-raw.v0.1.2"
RAW_MANIFEST_SCHEMA_VERSION = "pharos.quiet-negative-raw-manifest.v1"
VALID_STATUS = "validated"
MIN_CONTROL_ROWS = 50_000
PREREGISTRATION_RELATIVE_PATH = (
    "pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md"
)
PREREGISTRATION_SHA256 = "68e4f2d3359a5c4f208426d80a56f58788bdea6003e07ae0a75dc68cbcc259eb"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_strings(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _atomic_target(path: Path) -> tuple[int, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    return descriptor, Path(temporary)


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write a parquet file using a same-filesystem atomic replace."""
    fd, temporary = _atomic_target(path)
    os.close(fd)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(text: str, path: Path) -> None:
    """Write UTF-8 text using a same-filesystem atomic replace."""
    fd, temporary = _atomic_target(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_yaml(payload: Mapping[str, Any], path: Path) -> None:
    atomic_write_text(yaml.safe_dump(dict(payload), sort_keys=False), path)


def raw_manifest_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(cache_path.suffix + ".manifest.yaml")


def write_raw_checkpoint(
    *,
    cache_path: Path,
    frame: pd.DataFrame,
    query_traces: Sequence[Mapping[str, Any]],
    gaia_rows: int,
    retrieved_at_utc: str,
    generating_command: str,
) -> Path:
    """Atomically checkpoint bounded remote acquisition with exact provenance."""
    validation.validate_exact_columns(
        frame, validation.JOINED_SOURCE_COLUMNS, context="raw checkpoint"
    )
    if frame["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("raw checkpoint contains duplicate source identifiers")
    atomic_write_parquet(frame, cache_path)
    manifest = {
        "schema_version": RAW_MANIFEST_SCHEMA_VERSION,
        "status": "checkpoint",
        "pre_registration": {
            "path": PREREGISTRATION_RELATIVE_PATH,
            "sha256": PREREGISTRATION_SHA256,
        },
        "retrieved_at_utc": retrieved_at_utc,
        "generating_command": generating_command,
        "catalog_releases": {
            "gaia": "Gaia DR3",
            "allwise": "AllWISE Source Catalog",
            "tmass": "2MASS All-Sky Point Source Catalog",
        },
        "artifact": {
            "path": cache_path.name,
            "sha256": sha256_file(cache_path),
            "row_count": int(len(frame)),
            "columns": list(frame.columns),
            "schema_version": RAW_SCHEMA_VERSION,
        },
        "cursor_source_id": int(frame["gaia_dr3_source_id"].max()) if len(frame) else 0,
        "gaia_rows": int(gaia_rows),
        "query_traces": [dict(trace) for trace in query_traces],
        "limits": {"network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK},
    }
    manifest_path = raw_manifest_path(cache_path)
    validate_raw_manifest(manifest)
    atomic_write_yaml(manifest, manifest_path)
    return manifest_path


def validate_raw_manifest(payload: Any) -> Mapping[str, Any]:
    manifest = _require_keys(
        payload,
        {
            "schema_version",
            "status",
            "pre_registration",
            "retrieved_at_utc",
            "generating_command",
            "catalog_releases",
            "artifact",
            "cursor_source_id",
            "gaia_rows",
            "query_traces",
            "limits",
        },
        context="raw manifest",
    )
    if manifest["schema_version"] != RAW_MANIFEST_SCHEMA_VERSION:
        raise ValueError("raw manifest schema_version is not supported")
    if manifest["status"] != "checkpoint":
        raise ValueError("raw manifest status must be checkpoint")
    prereg = _require_keys(
        manifest["pre_registration"], {"path", "sha256"}, context="raw pre_registration"
    )
    if prereg["path"] != PREREGISTRATION_RELATIVE_PATH:
        raise ValueError("raw pre-registration path mismatch")
    if prereg["sha256"] != PREREGISTRATION_SHA256:
        raise ValueError("raw pre-registration SHA-256 mismatch")
    _validate_timestamp(manifest["retrieved_at_utc"])
    _validate_generating_command(manifest["generating_command"])
    releases = _require_keys(
        manifest["catalog_releases"],
        {"gaia", "allwise", "tmass"},
        context="raw catalog_releases",
    )
    if not all(isinstance(value, str) and value for value in releases.values()):
        raise ValueError("raw catalog releases must be non-empty strings")
    descriptor = _require_keys(
        manifest["artifact"],
        {"path", "sha256", "row_count", "columns", "schema_version"},
        context="raw artifact",
    )
    _require_relative_path(descriptor["path"], context="raw artifact.path")
    _require_sha256(descriptor["sha256"], context="raw artifact.sha256")
    if descriptor["schema_version"] != RAW_SCHEMA_VERSION:
        raise ValueError("raw artifact schema_version is not supported")
    if not isinstance(descriptor["row_count"], int) or descriptor["row_count"] < 0:
        raise ValueError("raw artifact row_count must be non-negative")
    if descriptor["columns"] != list(validation.JOINED_SOURCE_COLUMNS):
        raise ValueError("raw artifact columns do not match the registered schema")
    for field in ("cursor_source_id", "gaia_rows"):
        if not isinstance(manifest[field], int) or manifest[field] < 0:
            raise ValueError(f"raw {field} must be a non-negative integer")
    traces = manifest["query_traces"]
    if not isinstance(traces, list):
        raise TypeError("raw query_traces must be a list")
    for index, entry in enumerate(traces):
        trace = _require_keys(
            entry,
            {"service", "query_sha256", "response_rows"},
            context=f"raw query_traces[{index}]",
        )
        if not isinstance(trace["service"], str) or not trace["service"]:
            raise ValueError("raw trace service must be non-empty")
        _require_sha256(trace["query_sha256"], context="raw trace query_sha256")
        if not isinstance(trace["response_rows"], int) or trace["response_rows"] < 0:
            raise ValueError("raw trace response_rows must be non-negative")
    limits = _require_keys(
        manifest["limits"], {"network_source_chunk_max"}, context="raw limits"
    )
    if limits["network_source_chunk_max"] != validation.MAX_NETWORK_SOURCE_CHUNK:
        raise ValueError("raw network chunk limit mismatch")
    return manifest


def load_raw_checkpoint(cache_path: Path) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    manifest_path = raw_manifest_path(cache_path)
    if not cache_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("complete raw checkpoint pair not found")
    manifest = validate_raw_manifest(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    )
    descriptor = manifest["artifact"]
    if descriptor["path"] != cache_path.name:
        raise ValueError("raw checkpoint manifest names a different artifact")
    if sha256_file(cache_path) != descriptor["sha256"]:
        raise ValueError("raw checkpoint SHA-256 mismatch")
    frame = pd.read_parquet(cache_path)
    validation.validate_exact_columns(
        frame, validation.JOINED_SOURCE_COLUMNS, context="raw checkpoint"
    )
    if len(frame) != descriptor["row_count"]:
        raise ValueError("raw checkpoint row count mismatch")
    if frame["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("raw checkpoint contains duplicate source identifiers")
    expected_cursor = int(frame["gaia_dr3_source_id"].max()) if len(frame) else 0
    if manifest["cursor_source_id"] != expected_cursor:
        raise ValueError("raw checkpoint cursor mismatch")
    return frame, manifest


def _artifact_descriptor(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    if path.is_absolute():
        artifact_path = path.name
    else:
        artifact_path = path.as_posix()
    return {
        "path": artifact_path,
        "sha256": sha256_file(path),
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "schema_version": CONTROL_SCHEMA_VERSION,
    }


def build_control_manifest(
    *,
    control_path: Path,
    controls: pd.DataFrame,
    exclusions_path: Path,
    exclusions: pd.DataFrame,
    retrieved_at_utc: str,
    generating_command: str,
    query_provenance: list[dict[str, Any]],
    filter_counts: dict[str, int],
) -> dict[str, Any]:
    """Create the exact v1 manifest after both parquet files exist."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": VALID_STATUS,
        "pre_registration": {
            "path": PREREGISTRATION_RELATIVE_PATH,
            "sha256": PREREGISTRATION_SHA256,
        },
        "retrieved_at_utc": retrieved_at_utc,
        "generating_command": generating_command,
        "catalog_releases": {
            "gaia": "Gaia DR3",
            "allwise": "AllWISE Source Catalog",
            "tmass": "2MASS All-Sky Point Source Catalog",
            "simbad": f"SIMBAD live database at {retrieved_at_utc}",
            "chen": "VizieR J/ApJS/211/25/catalog; 2021-08-10 release",
        },
        "artifacts": {
            "controls": _artifact_descriptor(control_path, controls),
            "exclusions": _artifact_descriptor(exclusions_path, exclusions),
        },
        "query_provenance": query_provenance,
        "filter_counts": filter_counts,
        "limits": {
            "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
            "retained_matches_per_source_catalog_max": (
                validation.MAX_MATCHES_PER_SOURCE_CATALOG
            ),
            "control_minimum_rows": MIN_CONTROL_ROWS,
        },
    }


def _require_keys(value: Any, expected: set[str], *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")
    actual = {str(key) for key in value.keys()}
    if actual != expected:
        raise ValueError(
            f"{context} schema mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return value


def _require_sha256(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return value


def _require_relative_path(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{context} must not be absolute or escape its artifact directory")
    return value


def _validate_generating_command(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("generating_command must be a non-empty string")
    for token in shlex.split(value):
        if Path(token).is_absolute():
            raise ValueError("generating_command must not contain absolute workstation paths")
    return value


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("retrieved_at_utc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retrieved_at_utc is not valid ISO-8601") from exc
    return value


def _validate_artifact_descriptor(value: Any, *, context: str) -> Mapping[str, Any]:
    descriptor = _require_keys(
        value,
        {"path", "sha256", "row_count", "columns", "schema_version"},
        context=context,
    )
    _require_relative_path(descriptor["path"], context=f"{context}.path")
    _require_sha256(descriptor["sha256"], context=f"{context}.sha256")
    if not isinstance(descriptor["row_count"], int) or descriptor["row_count"] < 0:
        raise ValueError(f"{context}.row_count must be a non-negative integer")
    columns = descriptor["columns"]
    if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
        raise TypeError(f"{context}.columns must be a list of strings")
    if descriptor["schema_version"] != CONTROL_SCHEMA_VERSION:
        raise ValueError(f"{context}.schema_version is not supported")
    return descriptor


def validate_control_manifest(payload: Any) -> Mapping[str, Any]:
    """Validate every manifest field and reject unknown fields recursively."""
    manifest = _require_keys(
        payload,
        {
            "schema_version",
            "status",
            "pre_registration",
            "retrieved_at_utc",
            "generating_command",
            "catalog_releases",
            "artifacts",
            "query_provenance",
            "filter_counts",
            "limits",
        },
        context="manifest",
    )
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError("manifest schema_version is not supported")
    if manifest["status"] != VALID_STATUS:
        raise ValueError("control artifact status must be validated")

    prereg = _require_keys(
        manifest["pre_registration"], {"path", "sha256"}, context="pre_registration"
    )
    if prereg["path"] != PREREGISTRATION_RELATIVE_PATH:
        raise ValueError("pre-registration path does not match the frozen v0.1.2 specification")
    if prereg["sha256"] != PREREGISTRATION_SHA256:
        raise ValueError("pre-registration SHA-256 does not match the frozen v0.1.2 record")

    _validate_timestamp(manifest["retrieved_at_utc"])
    _validate_generating_command(manifest["generating_command"])

    releases = _require_keys(
        manifest["catalog_releases"],
        {"gaia", "allwise", "tmass", "simbad", "chen"},
        context="catalog_releases",
    )
    if not all(isinstance(value, str) and value for value in releases.values()):
        raise ValueError("catalog release identifiers must be non-empty strings")

    artifacts = _require_keys(
        manifest["artifacts"], {"controls", "exclusions"}, context="artifacts"
    )
    _validate_artifact_descriptor(artifacts["controls"], context="artifacts.controls")
    _validate_artifact_descriptor(artifacts["exclusions"], context="artifacts.exclusions")

    provenance = manifest["query_provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise ValueError("query_provenance must be a non-empty list")
    for index, entry in enumerate(provenance):
        item = _require_keys(
            entry,
            {"service", "request_count", "query_sha256", "response_rows"},
            context=f"query_provenance[{index}]",
        )
        if not isinstance(item["service"], str) or not item["service"]:
            raise ValueError("query provenance service must be non-empty")
        if not isinstance(item["request_count"], int) or item["request_count"] < 1:
            raise ValueError("query provenance request_count must be positive")
        if not isinstance(item["response_rows"], int) or item["response_rows"] < 0:
            raise ValueError("query provenance response_rows must be non-negative")
        _require_sha256(item["query_sha256"], context="query provenance query_sha256")

    counts = _require_keys(
        manifest["filter_counts"],
        {
            "gaia_rows",
            "joined_rows",
            "after_bp_rp_rows",
            "simbad_excluded_sources",
            "chen_excluded_sources",
            "final_rows",
        },
        context="filter_counts",
    )
    if not all(isinstance(value, int) and value >= 0 for value in counts.values()):
        raise ValueError("filter counts must be non-negative integers")

    limits = _require_keys(
        manifest["limits"],
        {
            "network_source_chunk_max",
            "retained_matches_per_source_catalog_max",
            "control_minimum_rows",
        },
        context="limits",
    )
    expected_limits = {
        "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
        "retained_matches_per_source_catalog_max": validation.MAX_MATCHES_PER_SOURCE_CATALOG,
        "control_minimum_rows": MIN_CONTROL_ROWS,
    }
    if dict(limits) != expected_limits:
        raise ValueError("manifest limits do not match the frozen v0.1.2 limits")
    return manifest


def load_control_artifact(manifest_path: Path) -> pd.DataFrame:
    """Load a control population only after exact manifest and hash validation.

    Legacy parquet caches have no conformant manifest and therefore cannot be
    consumed by calibration through this boundary.
    """
    if not manifest_path.is_file():
        raise FileNotFoundError(f"conformant control manifest not found: {manifest_path.name}")
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest = validate_control_manifest(payload)
    artifacts = manifest["artifacts"]
    control_descriptor = artifacts["controls"]
    exclusion_descriptor = artifacts["exclusions"]
    control_path = manifest_path.parent / control_descriptor["path"]
    exclusion_path = manifest_path.parent / exclusion_descriptor["path"]

    for path, descriptor, label in (
        (control_path, control_descriptor, "controls"),
        (exclusion_path, exclusion_descriptor, "exclusions"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"manifest-named {label} artifact is missing")
        if sha256_file(path) != descriptor["sha256"]:
            raise ValueError(f"{label} artifact SHA-256 mismatch")

    controls = pd.read_parquet(control_path)
    exclusions = pd.read_parquet(exclusion_path)
    if len(controls) != control_descriptor["row_count"]:
        raise ValueError("controls artifact row count does not match manifest")
    if len(exclusions) != exclusion_descriptor["row_count"]:
        raise ValueError("exclusions artifact row count does not match manifest")
    if list(controls.columns) != control_descriptor["columns"]:
        raise ValueError("controls artifact columns do not match manifest")
    if list(exclusions.columns) != exclusion_descriptor["columns"]:
        raise ValueError("exclusions artifact columns do not match manifest")
    validation.validate_control_artifact(controls, minimum_rows=MIN_CONTROL_ROWS)
    validation.validate_exclusions(exclusions)
    return controls

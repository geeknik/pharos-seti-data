"""Fail-closed, durable artifacts for quiet-negative control releases."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import yaml

from pharos import validation

CONTROL_SCHEMA_VERSION = "pharos.quiet-negative.v0.1.2"
MANIFEST_SCHEMA_VERSION = "pharos.quiet-negative-manifest.v3"
RAW_SCHEMA_VERSION = "pharos.quiet-negative-raw.v0.1.2"
RAW_MANIFEST_SCHEMA_VERSION = "pharos.quiet-negative-raw-manifest.v2"
VALID_STATUS = "validated"
MIN_CONTROL_ROWS = 50_000
MAX_YAML_BYTES = 1_048_576
MAX_PARQUET_BYTES = 2_147_483_648
PREREGISTRATION_RELATIVE_PATH = "pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md"
PREREGISTRATION_SHA256 = "68e4f2d3359a5c4f208426d80a56f58788bdea6003e07ae0a75dc68cbcc259eb"
GAIA_ENDPOINT = "https://gea.esac.esa.int/tap-server/tap"
SIMBAD_ENDPOINT = "https://simbad.cds.unistra.fr/simbad/sim-tap"
VIZIER_ENDPOINT = "https://vizier.cds.unistra.fr/viz-bin/votable"
SERVICE_ENDPOINTS = {
    "Gaia TAP joined": GAIA_ENDPOINT,
    "SIMBAD": SIMBAD_ENDPOINT,
    "VizieR Chen2014": VIZIER_ENDPOINT,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

@dataclass(frozen=True)
class TrustedRawCheckpoint:
    """Exact identity of one reviewed historical acquisition checkpoint."""

    git_commit: str
    source_tree_sha256: str
    uv_lock_sha256: str
    artifact_sha256: str
    manifest_sha256: str
    content_sha256: str
    row_count: int

    @property
    def producer_software(self) -> dict[str, str]:
        return {
            "git_commit": self.git_commit,
            "source_tree_sha256": self.source_tree_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
        }


@dataclass(frozen=True)
class TrustedReleaseArtifact:
    """Exact byte and semantic identity of one artifact in a reviewed release."""

    path: str
    sha256: str
    row_count: int
    columns: tuple[str, ...]
    schema_version: str
    content_sha256: str

    @property
    def descriptor(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class TrustedFinalRelease:
    """Reviewed immutable release allowed across later compatible runtimes."""

    release_id: str
    manifest_sha256: str
    producer_software: tuple[str, str, str]
    raw_candidates: TrustedReleaseArtifact
    controls: TrustedReleaseArtifact
    exclusions: TrustedReleaseArtifact
    query_provenance_sha256: str
    gaia_query_hashes_sha256: str
    simbad_query_sha256: str
    simbad_raw_response_rows: int
    simbad_normalized_rows: int
    chen_query_sha256: str
    chen_response_rows: int
    chen_normalized_rows: int

    @property
    def software(self) -> dict[str, str]:
        commit, source_tree, lock = self.producer_software
        return {
            "git_commit": commit,
            "source_tree_sha256": source_tree,
            "uv_lock_sha256": lock,
        }


@dataclass(frozen=True)
class AuthorizedControlRelease:
    """Registry-authorized controls and their verified immutable paths."""

    release_id: str
    manifest_path: Path
    controls_path: Path
    controls_sha256: str
    controls_descriptor: TrustedReleaseArtifact
    controls: pd.DataFrame


# Exact reviewed checkpoint allow-list. Failed pilots and acquisition
# checkpoints are intentionally absent; their identities remain only in the
# non-release failure record and cannot authorize a public loader.
TRUSTED_RAW_CHECKPOINTS: tuple[TrustedRawCheckpoint, ...] = ()


# Exact reviewed final-release allow-list. The failed v0.1.2 hardened pilot is
# not a release and is deliberately absent, so later runtimes reject it.
TRUSTED_FINAL_RELEASES: tuple[TrustedFinalRelease, ...] = ()


class ReleaseRegistryError(ValueError):
    """The immutable final-release authorization registry is malformed."""



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


def sha256_frame(frame: pd.DataFrame) -> str:
    """Hash response content independently of Parquet serialization."""
    digest = hashlib.sha256()
    digest.update("\n".join(str(column) for column in frame.columns).encode("utf-8"))
    digest.update(b"\0")
    digest.update("\n".join(str(dtype) for dtype in frame.dtypes).encode("utf-8"))
    digest.update(b"\0")
    digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return digest.hexdigest()


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_repository_path(path: Path, *, label: str) -> Path:
    """Resolve a path inside the repository and reject every symlink component."""
    root = repository_root()
    absolute = path if path.is_absolute() else root / path
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the repository") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ValueError(f"{label} path contains a symlink")
    resolved = absolute.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} resolves outside the repository")
    return resolved


def software_provenance() -> dict[str, str]:
    root = repository_root()
    lock = root / "uv.lock"
    if not lock.is_file() or lock.is_symlink():
        raise RuntimeError("trusted uv.lock is missing or is a symlink")
    dirty = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "src/pharos",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if dirty.stdout:
        raise RuntimeError("refusing software provenance from a dirty source/config/lock tree")
    completed = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "--",
            "src/pharos",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    commit = completed.stdout.strip()
    if _GIT_COMMIT_RE.fullmatch(commit) is None:
        raise RuntimeError("git did not return a full commit identifier")
    source_digest = hashlib.sha256()
    source_paths = [root / "pyproject.toml", *sorted((root / "src" / "pharos").glob("*.py"))]
    for path in source_paths:
        relative = path.relative_to(root).as_posix()
        source_digest.update(relative.encode("utf-8"))
        source_digest.update(b"\0")
        source_digest.update(sha256_file(path).encode("ascii"))
        source_digest.update(b"\n")
    return {
        "git_commit": commit,
        "source_tree_sha256": source_digest.hexdigest(),
        "uv_lock_sha256": sha256_file(lock),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_target(path: Path) -> tuple[int, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    return descriptor, Path(temporary)


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Durably replace a mutable checkpoint using a same-filesystem rename."""
    fd, temporary = _atomic_target(path)
    os.close(fd)
    try:
        frame.to_parquet(temporary, index=False)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(text: str, path: Path) -> None:
    fd, temporary = _atomic_target(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_yaml(payload: Mapping[str, Any], path: Path) -> None:
    atomic_write_text(yaml.safe_dump(dict(payload), sort_keys=False), path)


def write_content_addressed_parquet(frame: pd.DataFrame, *, directory: Path, prefix: str) -> Path:
    """Durably install an immutable content-addressed Parquet without overwrite."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("artifact prefix is invalid")
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{prefix}.", suffix=".tmp", dir=directory)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        frame.to_parquet(temporary_path, index=False)
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        digest = sha256_file(temporary_path)
        target = directory / f"{prefix}.{digest}.parquet"
        try:
            os.link(temporary_path, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileExistsError(
                f"refusing conflicting artifact generation: {target.name}"
            ) from exc
        temporary_path.unlink()
        _fsync_directory(directory)
        return target
    finally:
        temporary_path.unlink(missing_ok=True)


def write_exclusive_yaml(payload: Mapping[str, Any], path: Path) -> None:
    """Durably create a final manifest, refusing an existing generation."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing final manifest: {path.name}")
    fd, temporary = _atomic_target(path)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(dict(payload), handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileExistsError(
                f"refusing to overwrite existing final manifest: {path.name}"
            ) from exc
        temporary_path.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def install_release_directory_no_replace(staging: Path, output_dir: Path) -> None:
    """Publish staged regular files without ever replacing an existing directory.

    ``rename(2)`` may replace an empty destination directory on POSIX systems.  An
    exclusive ``mkdir`` reserves the final name instead; staged files are then
    hard-linked into that directory with the manifest installed last.  A crash
    before the final link leaves a fail-closed, manifest-less directory that a
    later build will refuse to overwrite.
    """
    if staging.is_symlink() or not staging.is_dir():
        raise ValueError("staging release must be a regular directory")
    if staging.parent.resolve(strict=True) != output_dir.parent.resolve(strict=True):
        raise ValueError("staging and release directories must share a parent filesystem")

    entries = sorted(staging.iterdir(), key=lambda item: item.name)
    manifests = [item for item in entries if item.name == "manifest.yaml"]
    payloads = [item for item in entries if item.name != "manifest.yaml"]
    if len(manifests) != 1 or not payloads:
        raise ValueError("staging release must contain a final manifest")
    for source in entries:
        mode = source.stat(follow_symlinks=False).st_mode
        if source.is_symlink() or not stat.S_ISREG(mode):
            raise ValueError("staging release may contain only regular non-symlink files")

    try:
        os.mkdir(output_dir, mode=0o755)
    except FileExistsError as exc:
        raise FileExistsError("refusing conflicting final release directory") from exc

    for source in payloads:
        destination = output_dir / source.name
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileExistsError("refusing conflicting final release content") from exc
    _fsync_directory(output_dir)

    manifest = manifests[0]
    try:
        os.link(manifest, output_dir / manifest.name, follow_symlinks=False)
    except FileExistsError as exc:
        raise FileExistsError("refusing conflicting final release manifest") from exc
    _fsync_directory(output_dir)

    for source in entries:
        source.unlink()
    staging.rmdir()
    _fsync_directory(output_dir.parent)


def _safe_contained_path(root: Path, relative: str, *, must_exist: bool) -> Path:
    _require_relative_path(relative, context="artifact path")
    if root.is_symlink():
        raise ValueError("artifact root must not be a symlink")
    resolved_root = root.resolve(strict=True)
    lexical = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ValueError("artifact path contains a symlink")
    resolved = lexical.resolve(strict=must_exist)
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("artifact path escapes its release directory")
    if must_exist and (not resolved.is_file() or resolved.is_symlink()):
        raise ValueError("artifact path is not a regular non-symlink file")
    return resolved


def _normalize_contained_reference(path: Path, *, root: Path) -> Path:
    """Resolve ancestor aliases while retaining checks on in-root path components."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        try:
            relative = resolved_path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("artifact path escapes its release directory") from exc
        return _safe_contained_path(resolved_root, relative.as_posix(), must_exist=True)
    return _safe_contained_path(root, relative.as_posix(), must_exist=True)


def _read_bounded_yaml_with_sha256(path: Path, *, root: Path) -> tuple[Any, str]:
    """Read and hash one bounded YAML inode through one no-follow descriptor."""
    safe = _normalize_contained_reference(path, root=root)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(safe, flags)
    except OSError as exc:
        raise ValueError("YAML artifact could not be opened without following symlinks") from exc
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("YAML artifact is not a regular file")
        if opened.st_size > MAX_YAML_BYTES:
            raise ValueError("YAML artifact exceeds the pre-materialization byte bound")
        raw = handle.read(MAX_YAML_BYTES + 1)
    if len(raw) > MAX_YAML_BYTES:
        raise ValueError("YAML artifact exceeds the pre-materialization byte bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("YAML artifact is not valid UTF-8") from exc
    for event in yaml.parse(text):
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML aliases and anchors are forbidden")
    return yaml.safe_load(text), hashlib.sha256(raw).hexdigest()


def _read_bounded_yaml(path: Path, *, root: Path) -> Any:
    payload, _ = _read_bounded_yaml_with_sha256(path, root=root)
    return payload


def _preflight_parquet(
    path: Path,
    *,
    root: Path,
    maximum_rows: int,
    expected_rows: int,
    expected_columns: Sequence[str],
) -> None:
    safe = _normalize_contained_reference(path, root=root)
    size = safe.stat().st_size
    if size > MAX_PARQUET_BYTES:
        raise ValueError("Parquet artifact exceeds the pre-materialization byte bound")
    metadata = pq.ParquetFile(safe).metadata
    if metadata.num_rows > maximum_rows:
        raise ValueError("Parquet artifact exceeds the pre-materialization row bound")
    if metadata.num_rows != expected_rows:
        raise ValueError("Parquet metadata row count does not match manifest")
    columns = list(pq.ParquetFile(safe).schema_arrow.names)
    if columns != list(expected_columns):
        raise ValueError("Parquet metadata columns do not match manifest")


def _read_verified_parquet(
    path: Path,
    *,
    root: Path,
    maximum_rows: int,
    descriptor: Mapping[str, Any],
) -> pd.DataFrame:
    """Hash, preflight, and materialize one contained inode through one descriptor."""
    safe = _normalize_contained_reference(path, root=root)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(safe, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("Parquet artifact is not a regular file")
        if opened.st_size > MAX_PARQUET_BYTES:
            raise ValueError("Parquet artifact exceeds the pre-materialization byte bound")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != descriptor["sha256"]:
                raise ValueError("Parquet artifact SHA-256 mismatch")
            handle.seek(0)
            parquet = pq.ParquetFile(handle)
            metadata = parquet.metadata
            if metadata.num_rows > maximum_rows:
                raise ValueError("Parquet artifact exceeds the pre-materialization row bound")
            if metadata.num_rows != descriptor["row_count"]:
                raise ValueError("Parquet metadata row count does not match manifest")
            if list(parquet.schema_arrow.names) != list(descriptor["columns"]):
                raise ValueError("Parquet metadata columns do not match manifest")
            handle.seek(0)
            return pd.read_parquet(handle)
    finally:
        os.close(fd)


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
    selection_target_rows: int,
    selection_strata: Sequence[Mapping[str, Any]],
) -> Path:
    validation.validate_joined_source_frame(frame, maximum_rows=validation.MAX_RAW_CONTROL_ROWS)
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
        "software": software_provenance(),
        "artifact": {
            "path": cache_path.name,
            "sha256": sha256_file(cache_path),
            "row_count": int(len(frame)),
            "columns": list(frame.columns),
            "schema_version": RAW_SCHEMA_VERSION,
        },
        "gaia_rows": int(gaia_rows),
        "selection_target_rows": int(selection_target_rows),
        "selection_strata": [dict(item) for item in selection_strata],
        "query_traces": [dict(trace) for trace in query_traces],
        "limits": {
            "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
            "raw_control_rows_max": validation.MAX_RAW_CONTROL_ROWS,
        },
    }
    manifest_path = raw_manifest_path(cache_path)
    validate_raw_manifest(manifest)
    atomic_write_yaml(manifest, manifest_path)
    return manifest_path


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
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"{context} must not be absolute or escape its artifact directory")
    return value


def _validate_generating_command(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("generating_command must be a non-empty string")
    for token in shlex.split(value):
        if Path(token).is_absolute():
            raise ValueError("generating_command must not contain absolute workstation paths")
    return value


def _validate_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be ISO-8601 UTC ending in Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp is not valid ISO-8601") from exc
    return parsed


def _validate_software(value: Any) -> Mapping[str, Any]:
    software = _require_keys(
        value,
        {"git_commit", "source_tree_sha256", "uv_lock_sha256"},
        context="software",
    )
    if (
        not isinstance(software["git_commit"], str)
        or _GIT_COMMIT_RE.fullmatch(software["git_commit"]) is None
    ):
        raise ValueError("software.git_commit must be a full lowercase commit")
    _require_sha256(software["source_tree_sha256"], context="software.source_tree_sha256")
    _require_sha256(software["uv_lock_sha256"], context="software.uv_lock_sha256")
    return software


def _trusted_raw_checkpoint(
    producer: Mapping[str, Any],
    *,
    artifact_sha256: str,
    manifest_sha256: str,
    row_count: int,
    content_sha256: str | None = None,
) -> TrustedRawCheckpoint | None:
    normalized = {str(key): str(item) for key, item in producer.items()}
    for trusted in _validated_raw_checkpoint_registry():
        if (
            normalized == trusted.producer_software
            and artifact_sha256 == trusted.artifact_sha256
            and manifest_sha256 == trusted.manifest_sha256
            and row_count == trusted.row_count
            and (content_sha256 is None or content_sha256 == trusted.content_sha256)
        ):
            return trusted
    return None


def _trace_identity_sha256(traces: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    keys = (
        "service",
        "endpoint",
        "query_sha256",
        "input_sha256",
        "response_sha256",
        "response_rows",
        "requested_at_utc",
        "received_at_utc",
    )
    for trace in traces:
        for key in keys:
            digest.update(str(trace[key]).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def _registry_sha256(value: Any, *, field: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise ReleaseRegistryError(f"release registry {field} must be a non-zero SHA-256")
    return value


def _validate_registry_artifact(
    value: Any,
    *,
    field: str,
    expected_schema: str,
    expected_columns: tuple[str, ...],
    minimum_rows: int,
    maximum_rows: int,
) -> TrustedReleaseArtifact:
    if type(value) is not TrustedReleaseArtifact:
        raise ReleaseRegistryError(f"release registry {field} has an invalid artifact type")
    if type(value.path) is not str:
        raise ReleaseRegistryError(f"release registry {field}.path must be a string")
    try:
        path = _require_relative_path(value.path, context=f"release registry {field}.path")
    except (TypeError, ValueError) as exc:
        raise ReleaseRegistryError(f"release registry {field}.path is invalid") from exc
    digest = _registry_sha256(value.sha256, field=f"{field}.sha256")
    if path != f"{path.split('.', 1)[0]}.{digest}.parquet":
        raise ReleaseRegistryError(f"release registry {field}.path is not content-addressed")
    if (
        not isinstance(value.row_count, int)
        or isinstance(value.row_count, bool)
        or not minimum_rows <= value.row_count <= maximum_rows
    ):
        raise ReleaseRegistryError(f"release registry {field}.row_count is invalid")
    if (
        type(value.columns) is not tuple
        or not all(type(column) is str and column for column in value.columns)
        or value.columns != expected_columns
    ):
        raise ReleaseRegistryError(f"release registry {field}.columns do not match schema")
    if type(value.schema_version) is not str or value.schema_version != expected_schema:
        raise ReleaseRegistryError(f"release registry {field}.schema_version is invalid")
    _registry_sha256(value.content_sha256, field=f"{field}.content_sha256")
    return value


def _validated_final_release_registry() -> tuple[TrustedFinalRelease, ...]:
    registry = TRUSTED_FINAL_RELEASES
    if type(registry) is not tuple:
        raise ReleaseRegistryError("final release registry must be a tuple")
    release_ids: set[str] = set()
    for index, release in enumerate(registry):
        field = f"entries[{index}]"
        if type(release) is not TrustedFinalRelease:
            raise ReleaseRegistryError(f"release registry {field} has an invalid entry type")
        if type(release.release_id) is not str or not _RELEASE_ID_RE.fullmatch(
            release.release_id
        ):
            raise ReleaseRegistryError(f"release registry {field}.release_id is invalid")
        if release.release_id in release_ids:
            raise ReleaseRegistryError("release registry contains duplicate release identities")
        release_ids.add(release.release_id)
        _registry_sha256(release.manifest_sha256, field=f"{field}.manifest_sha256")
        software = release.producer_software
        if type(software) is not tuple or len(software) != 3:
            raise ReleaseRegistryError(f"release registry {field}.producer_software is invalid")
        git_commit, source_tree, lock = software
        if type(git_commit) is not str or not _GIT_COMMIT_RE.fullmatch(git_commit):
            raise ReleaseRegistryError(f"release registry {field}.git_commit is invalid")
        _registry_sha256(source_tree, field=f"{field}.source_tree_sha256")
        _registry_sha256(lock, field=f"{field}.uv_lock_sha256")
        raw = _validate_registry_artifact(
            release.raw_candidates,
            field=f"{field}.raw_candidates",
            expected_schema=RAW_SCHEMA_VERSION,
            expected_columns=validation.JOINED_SOURCE_COLUMNS,
            minimum_rows=1,
            maximum_rows=validation.MAX_RAW_CONTROL_ROWS,
        )
        controls = _validate_registry_artifact(
            release.controls,
            field=f"{field}.controls",
            expected_schema=CONTROL_SCHEMA_VERSION,
            expected_columns=validation.CONTROL_ARTIFACT_COLUMNS,
            minimum_rows=MIN_CONTROL_ROWS,
            maximum_rows=validation.MAX_FINAL_CONTROL_ROWS,
        )
        exclusions = _validate_registry_artifact(
            release.exclusions,
            field=f"{field}.exclusions",
            expected_schema=CONTROL_SCHEMA_VERSION,
            expected_columns=validation.EXCLUSION_COLUMNS,
            minimum_rows=0,
            maximum_rows=validation.MAX_EXCLUSION_ROWS,
        )
        if raw.row_count < controls.row_count:
            raise ReleaseRegistryError("release registry controls exceed raw candidate rows")
        for name in (
            "query_provenance_sha256",
            "gaia_query_hashes_sha256",
            "simbad_query_sha256",
            "chen_query_sha256",
        ):
            _registry_sha256(getattr(release, name), field=f"{field}.{name}")
        counts = (
            release.simbad_raw_response_rows,
            release.simbad_normalized_rows,
            release.chen_response_rows,
            release.chen_normalized_rows,
        )
        if any(
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 0 <= count <= validation.MAX_EXCLUSION_ROWS
            for count in counts
        ):
            raise ReleaseRegistryError(f"release registry {field} response counts are invalid")
        if (
            release.simbad_normalized_rows > release.simbad_raw_response_rows
            or release.chen_normalized_rows > release.chen_response_rows
            or release.simbad_normalized_rows + release.chen_normalized_rows
            > exclusions.row_count
        ):
            raise ReleaseRegistryError(
                f"release registry {field} response counts are inconsistent"
            )
    return registry


def _validated_raw_checkpoint_registry() -> tuple[TrustedRawCheckpoint, ...]:
    registry = TRUSTED_RAW_CHECKPOINTS
    if type(registry) is not tuple:
        raise ReleaseRegistryError("raw checkpoint registry must be a tuple")
    seen_entries: set[TrustedRawCheckpoint] = set()
    seen_artifacts: set[str] = set()
    seen_manifests: set[str] = set()
    seen_contents: set[str] = set()
    for index, checkpoint in enumerate(registry):
        field = f"raw_entries[{index}]"
        if type(checkpoint) is not TrustedRawCheckpoint:
            raise ReleaseRegistryError(
                f"raw checkpoint registry {field} has an invalid entry type"
            )
        software = (
            checkpoint.git_commit,
            checkpoint.source_tree_sha256,
            checkpoint.uv_lock_sha256,
        )
        git_commit, source_tree, lock = software
        if type(git_commit) is not str or not _GIT_COMMIT_RE.fullmatch(git_commit):
            raise ReleaseRegistryError(
                f"raw checkpoint registry {field}.git_commit is invalid"
            )
        _registry_sha256(source_tree, field=f"{field}.source_tree_sha256")
        _registry_sha256(lock, field=f"{field}.uv_lock_sha256")
        artifact = _registry_sha256(
            checkpoint.artifact_sha256,
            field=f"{field}.artifact_sha256",
        )
        manifest = _registry_sha256(
            checkpoint.manifest_sha256,
            field=f"{field}.manifest_sha256",
        )
        content = _registry_sha256(
            checkpoint.content_sha256,
            field=f"{field}.content_sha256",
        )
        if (
            not isinstance(checkpoint.row_count, int)
            or isinstance(checkpoint.row_count, bool)
            or not 1 <= checkpoint.row_count <= validation.MAX_RAW_CONTROL_ROWS
        ):
            raise ReleaseRegistryError(
                f"raw checkpoint registry {field}.row_count is invalid"
            )
        if checkpoint in seen_entries:
            raise ReleaseRegistryError("raw checkpoint registry contains a duplicate entry")
        seen_entries.add(checkpoint)
        if artifact in seen_artifacts:
            raise ReleaseRegistryError(
                "raw checkpoint registry contains a duplicate artifact identity"
            )
        if manifest in seen_manifests:
            raise ReleaseRegistryError(
                "raw checkpoint registry contains a duplicate manifest identity"
            )
        if content in seen_contents:
            raise ReleaseRegistryError(
                "raw checkpoint registry contains a duplicate semantic identity"
            )
        seen_artifacts.add(artifact)
        seen_manifests.add(manifest)
        seen_contents.add(content)
    return registry


def _trusted_final_release(
    release_id: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
) -> TrustedFinalRelease | None:
    if not isinstance(release_id, str) or not release_id:
        raise ValueError("release identity must be a non-empty registry key")
    if not _RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("release identity has invalid syntax")
    registry = _validated_final_release_registry()
    matches = [release for release in registry if release.release_id == release_id]
    if len(matches) != 1:
        raise ValueError("release identity is not registry-authorized")
    trusted = matches[0]
    if manifest_sha256 != trusted.manifest_sha256:
        return None
    if dict(manifest["software"]) != trusted.software:
        return None
    expected = {
        "raw_candidates": trusted.raw_candidates.descriptor,
        "controls": trusted.controls.descriptor,
        "exclusions": trusted.exclusions.descriptor,
    }
    if dict(manifest["artifacts"]) != expected:
        return None
    traces = manifest["query_provenance"]
    if not isinstance(traces, list):
        return None
    if _trace_identity_sha256(traces) != trusted.query_provenance_sha256:
        return None
    return trusted


def _validate_trace(value: Any, *, context: str) -> Mapping[str, Any]:
    trace = _require_keys(
        value,
        {
            "service",
            "endpoint",
            "query_sha256",
            "input_sha256",
            "response_sha256",
            "response_rows",
            "requested_at_utc",
            "received_at_utc",
        },
        context=context,
    )
    service = trace["service"]
    if service not in SERVICE_ENDPOINTS or trace["endpoint"] != SERVICE_ENDPOINTS[service]:
        raise ValueError(f"{context}: service endpoint mismatch")
    for key in ("query_sha256", "input_sha256", "response_sha256"):
        _require_sha256(trace[key], context=f"{context}.{key}")
        if trace[key] == "0" * 64:
            raise ValueError(f"{context}.{key}: all-zero provenance digest is forbidden")
    if (
        not isinstance(trace["response_rows"], int)
        or isinstance(trace["response_rows"], bool)
        or trace["response_rows"] < 0
    ):
        raise ValueError(f"{context}: response_rows must be non-negative")
    if trace["response_rows"] > validation.MAX_EXCLUSION_ROWS:
        raise ValueError(f"{context}: response row bound exceeded")
    service_limit = {
        "Gaia TAP joined": validation.MAX_NETWORK_SOURCE_CHUNK,
        "SIMBAD": validation.MAX_NETWORK_SOURCE_CHUNK * validation.MAX_MATCHES_PER_SOURCE_CATALOG,
        "VizieR Chen2014": validation.MAX_CLI_SOURCE_IDS,
    }[service]
    if trace["response_rows"] > service_limit:
        raise ValueError(f"{context}: service-specific response row bound exceeded")
    if service == "Gaia TAP joined" and trace["input_sha256"] != trace["query_sha256"]:
        raise ValueError(f"{context}: Gaia input/query provenance mismatch")
    started = _validate_timestamp(trace["requested_at_utc"])
    finished = _validate_timestamp(trace["received_at_utc"])
    if finished < started:
        raise ValueError(f"{context}: response timestamp precedes request")
    return trace


def _validate_strata(value: Any, *, target_rows: int) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != 24:
        raise ValueError("selection_strata must contain exactly 24 fixed sky strata")
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _require_keys(
            raw,
            {
                "stratum_id",
                "longitude_min_deg",
                "longitude_max_deg",
                "hemisphere",
                "quota",
                "cursor_source_id",
                "collected_rows",
            },
            context=f"selection_strata[{index}]",
        )
        sid = item["stratum_id"]
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("selection stratum identifiers must be unique")
        seen.add(sid)
        if item["hemisphere"] not in {"north", "south"}:
            raise ValueError("selection stratum hemisphere is invalid")
        lower, upper = item["longitude_min_deg"], item["longitude_max_deg"]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lower, upper)):
            raise TypeError("selection longitude bounds must be numeric")
        if not (0.0 <= float(lower) < float(upper) <= 360.0):
            raise ValueError("selection longitude bounds are invalid")
        for key in ("quota", "cursor_source_id", "collected_rows"):
            if not isinstance(item[key], int) or isinstance(item[key], bool) or item[key] < 0:
                raise ValueError(f"selection {key} must be a non-negative integer")
        if item["collected_rows"] > item["quota"]:
            raise ValueError("selection stratum collected_rows exceeds quota")
        out.append(item)
    if sum(int(item["quota"]) for item in out) != target_rows:
        raise ValueError("selection stratum quotas do not sum to target")
    base_quota, remainder = divmod(target_rows, len(out))
    expected_quotas = [
        base_quota + (1 if index < remainder else 0) for index in range(len(out))
    ]
    if [int(item["quota"]) for item in out] != expected_quotas:
        raise ValueError("selection stratum quotas do not match deterministic allocation")
    expected = [
        (f"l{lower:03d}-{lower + 30:03d}-{hemisphere}", float(lower), float(lower + 30), hemisphere)
        for lower in range(0, 360, 30)
        for hemisphere in ("north", "south")
    ]
    actual = [
        (
            str(item["stratum_id"]),
            float(item["longitude_min_deg"]),
            float(item["longitude_max_deg"]),
            str(item["hemisphere"]),
        )
        for item in out
    ]
    if actual != expected:
        raise ValueError("selection strata do not match the fixed all-sky partition")
    if any(item["collected_rows"] > 0 and item["cursor_source_id"] <= 0 for item in out):
        raise ValueError("populated selection strata require a positive cursor")
    return out


def _rows_by_stratum(
    frame: pd.DataFrame, strata: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    counts: list[dict[str, Any]] = []
    assigned = pd.Series(False, index=frame.index)
    for item in strata:
        longitude = (frame["galactic_l"] >= float(item["longitude_min_deg"])) & (
            frame["galactic_l"] < float(item["longitude_max_deg"])
        )
        latitude = (
            frame["galactic_b"] > 20.0
            if item["hemisphere"] == "north"
            else frame["galactic_b"] < -20.0
        )
        selected = longitude & latitude
        if (assigned & selected).any():
            raise ValueError("a source belongs to multiple selection strata")
        assigned |= selected
        counts.append({"stratum_id": str(item["stratum_id"]), "row_count": int(selected.sum())})
    if not assigned.all():
        raise ValueError("a source falls outside every registered selection stratum")
    return counts


def _validate_retained_strata(
    value: Any, *, strata: Sequence[Mapping[str, Any]], expected_rows: int
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(strata):
        raise ValueError("retained_rows_by_stratum has the wrong shape")
    expected_ids = [str(item["stratum_id"]) for item in strata]
    out: list[Mapping[str, Any]] = []
    for index, raw in enumerate(value):
        item = _require_keys(
            raw, {"stratum_id", "row_count"}, context=f"retained_rows_by_stratum[{index}]"
        )
        if item["stratum_id"] != expected_ids[index]:
            raise ValueError("retained stratum identifier/order mismatch")
        if not isinstance(item["row_count"], int) or item["row_count"] < 0:
            raise ValueError("retained stratum row count must be non-negative")
        if item["row_count"] > strata[index]["quota"]:
            raise ValueError("retained stratum row count exceeds acquisition quota")
        out.append(item)
    if sum(int(item["row_count"]) for item in out) != expected_rows:
        raise ValueError("retained stratum counts do not sum to final rows")
    return out


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
            "software",
            "artifact",
            "gaia_rows",
            "selection_target_rows",
            "selection_strata",
            "query_traces",
            "limits",
        },
        context="raw manifest",
    )
    if (
        manifest["schema_version"] != RAW_MANIFEST_SCHEMA_VERSION
        or manifest["status"] != "checkpoint"
    ):
        raise ValueError("raw manifest version/status is not supported")
    _validate_preregistration(manifest["pre_registration"])
    _validate_timestamp(manifest["retrieved_at_utc"])
    _validate_generating_command(manifest["generating_command"])
    releases = _require_keys(
        manifest["catalog_releases"], {"gaia", "allwise", "tmass"}, context="raw releases"
    )
    if not all(isinstance(value, str) and value for value in releases.values()):
        raise ValueError("raw catalog release identifiers must be non-empty")
    _validate_software(manifest["software"])
    descriptor = _validate_artifact_descriptor(
        manifest["artifact"],
        context="raw artifact",
        schema_version=RAW_SCHEMA_VERSION,
        require_content_addressed=False,
    )
    if descriptor["columns"] != list(validation.JOINED_SOURCE_COLUMNS):
        raise ValueError("raw artifact columns do not match registered schema")
    for key in ("gaia_rows", "selection_target_rows"):
        if (
            not isinstance(manifest[key], int)
            or isinstance(manifest[key], bool)
            or manifest[key] < 1
        ):
            raise ValueError(f"raw {key} must be a positive integer")
    if manifest["selection_target_rows"] > validation.MAX_RAW_CONTROL_ROWS:
        raise ValueError("raw selection target exceeds registered bound")
    strata = _validate_strata(
        manifest["selection_strata"], target_rows=manifest["selection_target_rows"]
    )
    if sum(int(item["collected_rows"]) for item in strata) != descriptor["row_count"]:
        raise ValueError("raw stratum counts do not match artifact row count")
    if manifest["gaia_rows"] != descriptor["row_count"]:
        raise ValueError("raw Gaia count does not match artifact row count")
    traces = manifest["query_traces"]
    if not isinstance(traces, list):
        raise TypeError("raw query_traces must be a list")
    validated = [
        _validate_trace(item, context=f"raw query_traces[{i}]") for i, item in enumerate(traces)
    ]
    if sum(int(item["response_rows"]) for item in validated) != manifest["gaia_rows"]:
        raise ValueError("raw trace rows do not match Gaia row count")
    limits = _require_keys(
        manifest["limits"],
        {"network_source_chunk_max", "raw_control_rows_max"},
        context="raw limits",
    )
    if dict(limits) != {
        "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
        "raw_control_rows_max": validation.MAX_RAW_CONTROL_ROWS,
    }:
        raise ValueError("raw limits do not match runtime")
    return manifest


def _load_raw_checkpoint_record(
    cache_path: Path,
) -> tuple[pd.DataFrame, Mapping[str, Any], str]:
    manifest_path = raw_manifest_path(cache_path)
    root = cache_path.parent
    if not root.exists() or root.is_symlink():
        raise FileNotFoundError("safe raw checkpoint directory not found")
    if not cache_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("complete raw checkpoint pair not found")
    payload, manifest_sha256 = _read_bounded_yaml_with_sha256(manifest_path, root=root)
    manifest = validate_raw_manifest(payload)
    producer = dict(manifest["software"])
    descriptor = manifest["artifact"]
    if descriptor["path"] != cache_path.name:
        raise ValueError("raw checkpoint manifest names a different artifact")
    trusted = _trusted_raw_checkpoint(
        producer,
        artifact_sha256=str(descriptor["sha256"]),
        manifest_sha256=manifest_sha256,
        row_count=int(descriptor["row_count"]),
    )
    if trusted is None and producer != software_provenance():
        raise ValueError(
            "raw checkpoint software provenance/byte identity is not an approved checkpoint"
        )
    frame = _read_verified_parquet(
        cache_path,
        root=root,
        maximum_rows=validation.MAX_RAW_CONTROL_ROWS,
        descriptor=descriptor,
    )
    validation.validate_joined_source_frame(frame, maximum_rows=validation.MAX_RAW_CONTROL_ROWS)
    if trusted is not None and sha256_frame(frame) != trusted.content_sha256:
        raise ValueError("trusted raw checkpoint semantic content SHA-256 mismatch")
    actual_counts = _rows_by_stratum(frame, manifest["selection_strata"])
    for actual, registered in zip(actual_counts, manifest["selection_strata"], strict=True):
        if actual["row_count"] != registered["collected_rows"]:
            raise ValueError("raw checkpoint rows do not match stratum metadata")
        selected = frame[
            (frame["galactic_l"] >= registered["longitude_min_deg"])
            & (frame["galactic_l"] < registered["longitude_max_deg"])
            & (
                (frame["galactic_b"] > 20.0)
                if registered["hemisphere"] == "north"
                else (frame["galactic_b"] < -20.0)
            )
        ]
        if (
            not selected.empty
            and int(selected["gaia_dr3_source_id"].max()) != registered["cursor_source_id"]
        ):
            raise ValueError("raw checkpoint cursor does not match its stratum rows")
    return frame, manifest, manifest_sha256


def load_raw_checkpoint(cache_path: Path) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    frame, manifest, _ = _load_raw_checkpoint_record(cache_path)
    return frame, manifest


def load_raw_checkpoint_record(
    cache_path: Path,
) -> tuple[pd.DataFrame, Mapping[str, Any], str]:
    """Load a checkpoint plus the digest of its bounded, no-follow manifest read."""
    return _load_raw_checkpoint_record(cache_path)


def _artifact_descriptor(
    path: Path,
    frame: pd.DataFrame,
    *,
    schema_version: str = CONTROL_SCHEMA_VERSION,
) -> dict[str, Any]:
    digest = sha256_file(path)
    if path.name != f"{path.name.split('.', 1)[0]}.{digest}.parquet":
        raise ValueError("final Parquet filename is not content-addressed")
    return {
        "path": path.name,
        "sha256": digest,
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "schema_version": schema_version,
    }


def _validate_preregistration(value: Any) -> Mapping[str, Any]:
    prereg = _require_keys(value, {"path", "sha256"}, context="pre_registration")
    if (
        prereg["path"] != PREREGISTRATION_RELATIVE_PATH
        or prereg["sha256"] != PREREGISTRATION_SHA256
    ):
        raise ValueError("pre-registration binding does not match frozen v0.1.2")
    return prereg


def _validate_artifact_descriptor(
    value: Any,
    *,
    context: str,
    schema_version: str = CONTROL_SCHEMA_VERSION,
    require_content_addressed: bool = True,
) -> Mapping[str, Any]:
    descriptor = _require_keys(
        value,
        {"path", "sha256", "row_count", "columns", "schema_version"},
        context=context,
    )
    path = _require_relative_path(descriptor["path"], context=f"{context}.path")
    digest = _require_sha256(descriptor["sha256"], context=f"{context}.sha256")
    if require_content_addressed and path != f"{path.split('.', 1)[0]}.{digest}.parquet":
        raise ValueError(f"{context}.path is not content-addressed by its SHA-256")
    if not isinstance(descriptor["row_count"], int) or descriptor["row_count"] < 0:
        raise ValueError(f"{context}.row_count must be non-negative")
    if not isinstance(descriptor["columns"], list) or not all(
        isinstance(item, str) for item in descriptor["columns"]
    ):
        raise TypeError(f"{context}.columns must be strings")
    if descriptor["schema_version"] != schema_version:
        raise ValueError(f"{context}.schema_version is not supported")
    return descriptor


def build_control_manifest(
    *,
    raw_candidates_path: Path,
    raw_candidates: pd.DataFrame,
    control_path: Path,
    controls: pd.DataFrame,
    exclusions_path: Path,
    exclusions: pd.DataFrame,
    retrieved_at_utc: str,
    generating_command: str,
    query_provenance: list[dict[str, Any]],
    filter_counts: dict[str, int],
    selection_target_rows: int,
    selection_strata: list[dict[str, Any]],
    raw_input_provenance: dict[str, Any],
) -> dict[str, Any]:
    release_software = software_provenance()
    raw_descriptor = _artifact_descriptor(
        raw_candidates_path,
        raw_candidates,
        schema_version=RAW_SCHEMA_VERSION,
    )
    raw_input = _require_keys(
        raw_input_provenance,
        {
            "artifact_sha256",
            "checkpoint_manifest_sha256",
            "producer_software",
            "content_sha256",
        },
        context="raw input provenance",
    )
    input_content_sha256 = _require_sha256(
        raw_input["content_sha256"], context="raw input provenance.content_sha256"
    )
    if input_content_sha256 != sha256_frame(raw_candidates):
        raise ValueError("raw input semantic content does not match released raw candidates")
    release_raw_input = {
        "artifact_sha256": _require_sha256(
            raw_input["artifact_sha256"], context="raw input provenance.artifact_sha256"
        ),
        "checkpoint_manifest_sha256": _require_sha256(
            raw_input["checkpoint_manifest_sha256"],
            context="raw input provenance.checkpoint_manifest_sha256",
        ),
        "producer_software": dict(_validate_software(raw_input["producer_software"])),
        "content_sha256": input_content_sha256,
        "released_artifact_sha256": raw_descriptor["sha256"],
    }
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
        "software": release_software,
        "raw_input_provenance": release_raw_input,
        "selection": {
            "strategy": "galactic-longitude-hemisphere-v1",
            "target_rows": selection_target_rows,
            "strata": selection_strata,
            "retained_rows_by_stratum": _rows_by_stratum(controls, selection_strata),
        },
        "artifacts": {
            "raw_candidates": raw_descriptor,
            "controls": _artifact_descriptor(control_path, controls),
            "exclusions": _artifact_descriptor(exclusions_path, exclusions),
        },
        "query_provenance": query_provenance,
        "filter_counts": filter_counts,
        "limits": {
            "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
            "retained_matches_per_source_catalog_max": validation.MAX_MATCHES_PER_SOURCE_CATALOG,
            "control_minimum_rows": MIN_CONTROL_ROWS,
            "control_rows_max": validation.MAX_FINAL_CONTROL_ROWS,
            "exclusion_rows_max": validation.MAX_EXCLUSION_ROWS,
            "yaml_bytes_max": MAX_YAML_BYTES,
            "parquet_bytes_max": MAX_PARQUET_BYTES,
        },
    }


def validate_control_manifest(payload: Any) -> Mapping[str, Any]:
    manifest = _require_keys(
        payload,
        {
            "schema_version",
            "status",
            "pre_registration",
            "retrieved_at_utc",
            "generating_command",
            "catalog_releases",
            "software",
            "raw_input_provenance",
            "selection",
            "artifacts",
            "query_provenance",
            "filter_counts",
            "limits",
        },
        context="manifest",
    )
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION or manifest["status"] != VALID_STATUS:
        raise ValueError("control manifest version/status is not supported")
    _validate_preregistration(manifest["pre_registration"])
    _validate_timestamp(manifest["retrieved_at_utc"])
    _validate_generating_command(manifest["generating_command"])
    releases = _require_keys(
        manifest["catalog_releases"],
        {"gaia", "allwise", "tmass", "simbad", "chen"},
        context="catalog_releases",
    )
    expected_releases = {
        "gaia": "Gaia DR3",
        "allwise": "AllWISE Source Catalog",
        "tmass": "2MASS All-Sky Point Source Catalog",
        "simbad": f"SIMBAD live database at {manifest['retrieved_at_utc']}",
        "chen": validation.CHEN_EXCLUSION_RELEASE,
    }
    if dict(releases) != expected_releases:
        raise ValueError("catalog releases do not match the registered releases")
    _validate_software(manifest["software"])
    raw_input = _require_keys(
        manifest["raw_input_provenance"],
        {
            "artifact_sha256",
            "checkpoint_manifest_sha256",
            "producer_software",
            "content_sha256",
            "released_artifact_sha256",
        },
        context="raw_input_provenance",
    )
    checkpoint_artifact_sha256 = _require_sha256(
        raw_input["artifact_sha256"], context="raw_input_provenance.artifact_sha256"
    )
    checkpoint_manifest_sha256 = _require_sha256(
        raw_input["checkpoint_manifest_sha256"],
        context="raw_input_provenance.checkpoint_manifest_sha256",
    )
    _require_sha256(raw_input["content_sha256"], context="raw_input_provenance.content_sha256")
    released_artifact_sha256 = _require_sha256(
        raw_input["released_artifact_sha256"],
        context="raw_input_provenance.released_artifact_sha256",
    )
    raw_producer = _validate_software(raw_input["producer_software"])
    selection = _require_keys(
        manifest["selection"],
        {"strategy", "target_rows", "strata", "retained_rows_by_stratum"},
        context="selection",
    )
    if selection["strategy"] != "galactic-longitude-hemisphere-v1":
        raise ValueError("selection strategy is not registered")
    if (
        not isinstance(selection["target_rows"], int)
        or not 1 <= selection["target_rows"] <= validation.MAX_RAW_CONTROL_ROWS
    ):
        raise ValueError("selection target_rows is invalid")
    strata = _validate_strata(selection["strata"], target_rows=selection["target_rows"])
    if any(item["collected_rows"] != item["quota"] for item in strata):
        raise ValueError("final selection has an incomplete sky stratum")
    descriptors = _require_keys(
        manifest["artifacts"],
        {"raw_candidates", "controls", "exclusions"},
        context="artifacts",
    )
    raw_candidates = _validate_artifact_descriptor(
        descriptors["raw_candidates"],
        context="artifacts.raw_candidates",
        schema_version=RAW_SCHEMA_VERSION,
    )
    controls = _validate_artifact_descriptor(descriptors["controls"], context="artifacts.controls")
    exclusions = _validate_artifact_descriptor(
        descriptors["exclusions"], context="artifacts.exclusions"
    )
    if raw_candidates["columns"] != list(validation.JOINED_SOURCE_COLUMNS):
        raise ValueError("raw candidate artifact columns do not match registered schema")
    if released_artifact_sha256 != raw_candidates["sha256"]:
        raise ValueError("raw input provenance does not bind the released raw artifact")
    trusted_checkpoint = _trusted_raw_checkpoint(
        raw_producer,
        artifact_sha256=checkpoint_artifact_sha256,
        manifest_sha256=checkpoint_manifest_sha256,
        row_count=int(raw_candidates["row_count"]),
        content_sha256=str(raw_input["content_sha256"]),
    )
    if trusted_checkpoint is None:
        raise ValueError("raw input provenance does not name an approved exact checkpoint")
    if controls["columns"] != list(validation.CONTROL_ARTIFACT_COLUMNS):
        raise ValueError("control artifact columns do not match registered schema")
    if exclusions["columns"] != list(validation.EXCLUSION_COLUMNS):
        raise ValueError("exclusion artifact columns do not match registered schema")
    provenance = manifest["query_provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise ValueError("query_provenance must be a non-empty list")
    traces = [
        _validate_trace(item, context=f"query_provenance[{i}]") for i, item in enumerate(provenance)
    ]
    if {str(item["service"]) for item in traces} != set(SERVICE_ENDPOINTS):
        raise ValueError("query provenance must bind Gaia, SIMBAD, and VizieR inputs")
    counts = _require_keys(
        manifest["filter_counts"],
        {
            "gaia_rows",
            "joined_rows",
            "after_bp_rp_rows",
            "simbad_excluded_sources",
            "chen_excluded_sources",
            "excluded_unique_sources",
            "final_rows",
        },
        context="filter_counts",
    )
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in counts.values()
    ):
        raise ValueError("filter counts must be non-negative integers")
    if not (
        counts["gaia_rows"] == counts["joined_rows"] == selection["target_rows"]
        and counts["joined_rows"] >= counts["after_bp_rp_rows"] >= counts["final_rows"]
        and counts["final_rows"] == counts["after_bp_rp_rows"] - counts["excluded_unique_sources"]
        and counts["excluded_unique_sources"]
        <= counts["simbad_excluded_sources"] + counts["chen_excluded_sources"]
        and raw_candidates["row_count"] == counts["joined_rows"]
        and controls["row_count"] == counts["final_rows"]
        and exclusions["row_count"] >= counts["excluded_unique_sources"]
    ):
        raise ValueError("manifest relational filter/artifact counts are inconsistent")
    _validate_retained_strata(
        selection["retained_rows_by_stratum"],
        strata=strata,
        expected_rows=counts["final_rows"],
    )
    gaia_trace_rows = sum(
        int(item["response_rows"]) for item in traces if item["service"] == "Gaia TAP joined"
    )
    if gaia_trace_rows != counts["gaia_rows"]:
        raise ValueError("Gaia provenance rows do not match filter counts")
    limits = _require_keys(
        manifest["limits"],
        {
            "network_source_chunk_max",
            "retained_matches_per_source_catalog_max",
            "control_minimum_rows",
            "control_rows_max",
            "exclusion_rows_max",
            "yaml_bytes_max",
            "parquet_bytes_max",
        },
        context="limits",
    )
    expected_limits = {
        "network_source_chunk_max": validation.MAX_NETWORK_SOURCE_CHUNK,
        "retained_matches_per_source_catalog_max": validation.MAX_MATCHES_PER_SOURCE_CATALOG,
        "control_minimum_rows": MIN_CONTROL_ROWS,
        "control_rows_max": validation.MAX_FINAL_CONTROL_ROWS,
        "exclusion_rows_max": validation.MAX_EXCLUSION_ROWS,
        "yaml_bytes_max": MAX_YAML_BYTES,
        "parquet_bytes_max": MAX_PARQUET_BYTES,
    }
    if dict(limits) != expected_limits:
        raise ValueError("manifest limits do not match runtime")
    return manifest


def _validate_release_query_provenance(
    manifest: Mapping[str, Any],
    raw_candidates: pd.DataFrame,
    exclusions: pd.DataFrame,
    *,
    trusted: TrustedFinalRelease | None,
) -> None:
    """Reconstruct request coverage from immutable inputs and reject gaps."""
    # Current-tree query builders are consulted only for untrusted/unpublished
    # releases. The exact reviewed release remains independent of later
    # producer refactors because its complete trace identity is immutable.
    producer_control_population: Any = None
    producer_sources: Any = None
    if trusted is None:
        from pharos import control_population as producer_control_population
        from pharos import sources as producer_sources

    traces = [
        _validate_trace(item, context=f"query_provenance[{index}]")
        for index, item in enumerate(manifest["query_provenance"])
    ]
    previous_received: datetime | None = None
    for trace in traces:
        requested = _validate_timestamp(trace["requested_at_utc"])
        if previous_received is not None and requested < previous_received:
            raise ValueError("query provenance requests are reordered or overlap")
        previous_received = _validate_timestamp(trace["received_at_utc"])

    registered_strata = manifest["selection"]["strata"]
    expected_gaia_count = sum(
        (int(item["quota"]) + validation.MAX_NETWORK_SOURCE_CHUNK - 1)
        // validation.MAX_NETWORK_SOURCE_CHUNK
        for item in registered_strata
    )
    bp_rp = validation.derive_bp_rp_controls(raw_candidates)
    expected_simbad_count = (
        len(bp_rp) + validation.MAX_NETWORK_SOURCE_CHUNK - 1
    ) // validation.MAX_NETWORK_SOURCE_CHUNK
    expected_services = (
        ["Gaia TAP joined"] * expected_gaia_count
        + ["SIMBAD"] * expected_simbad_count
        + ["VizieR Chen2014"]
    )
    if [str(trace["service"]) for trace in traces] != expected_services:
        raise ValueError("query provenance service count/order is incomplete")

    gaia_traces = traces[:expected_gaia_count]
    simbad_end = expected_gaia_count + expected_simbad_count
    simbad_traces = traces[expected_gaia_count:simbad_end]
    chen_trace = traces[simbad_end]

    # The raw artifact is stored in request order. Recreate the round-robin
    # stratum pagination, including each page size, cursor, and query binding.
    states: list[dict[str, Any]] = [
        {
            "stratum_id": str(item["stratum_id"]),
            "longitude_min_deg": float(item["longitude_min_deg"]),
            "longitude_max_deg": float(item["longitude_max_deg"]),
            "hemisphere": str(item["hemisphere"]),
            "quota": int(item["quota"]),
            "cursor_source_id": 0,
            "collected_rows": 0,
        }
        for item in registered_strata
    ]
    raw_offset = 0
    trace_offset = 0
    while any(item["collected_rows"] < item["quota"] for item in states):
        for index, state in enumerate(states):
            remaining = int(state["quota"]) - int(state["collected_rows"])
            if remaining <= 0:
                continue
            requested_rows = min(validation.MAX_NETWORK_SOURCE_CHUNK, remaining)
            trace = gaia_traces[trace_offset]
            trace_offset += 1
            if int(trace["response_rows"]) != requested_rows:
                raise ValueError("Gaia provenance page size does not match selection quota")
            page = raw_candidates.iloc[raw_offset : raw_offset + requested_rows]
            raw_offset += requested_rows
            if len(page) != requested_rows:
                raise ValueError("Gaia provenance pages do not cover the raw artifact")
            ids = page["gaia_dr3_source_id"].astype("int64")
            if not ids.is_monotonic_increasing or int(ids.iloc[0]) <= int(
                state["cursor_source_id"]
            ):
                raise ValueError("Gaia provenance page violates keyset order")
            longitude_ok = (page["galactic_l"] >= float(state["longitude_min_deg"])) & (
                page["galactic_l"] < float(state["longitude_max_deg"])
            )
            latitude_ok = (
                page["galactic_b"] > 20.0
                if state["hemisphere"] == "north"
                else page["galactic_b"] < -20.0
            )
            if not (longitude_ok & latitude_ok).all():
                raise ValueError("Gaia provenance page contains the wrong sky stratum")
            if trace["input_sha256"] != trace["query_sha256"]:
                raise ValueError("Gaia provenance input/query mismatch")
            if trusted is None:
                runtime_stratum = producer_sources.SamplingStratum(
                    stratum_id=state["stratum_id"],
                    longitude_min_deg=state["longitude_min_deg"],
                    longitude_max_deg=state["longitude_max_deg"],
                    hemisphere=state["hemisphere"],
                    quota=state["quota"],
                    cursor_source_id=state["cursor_source_id"],
                    collected_rows=state["collected_rows"],
                )
                query = producer_sources.build_quiet_negative_joined_adql(
                    requested_rows,
                    after_source_id=state["cursor_source_id"],
                    stratum=runtime_stratum,
                )
                expected_query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
                if trace["query_sha256"] != expected_query_sha256:
                    raise ValueError("Gaia provenance query does not match current producer")
            states[index] = {
                **state,
                "cursor_source_id": int(ids.iloc[-1]),
                "collected_rows": int(state["collected_rows"]) + requested_rows,
            }
    if raw_offset != len(raw_candidates) or trace_offset != len(gaia_traces):
        raise ValueError("Gaia provenance does not exactly cover raw candidates")
    for actual, registered in zip(states, registered_strata, strict=True):
        if (
            int(actual["cursor_source_id"]) != int(registered["cursor_source_id"])
            or int(actual["collected_rows"]) != int(registered["collected_rows"])
        ):
            raise ValueError("Gaia provenance cursor does not match final selection state")
    if trusted is not None:
        gaia_hash = sha256_strings([str(trace["query_sha256"]) for trace in gaia_traces])
        if gaia_hash != trusted.gaia_query_hashes_sha256:
            raise ValueError("trusted Gaia query provenance identity mismatch")

    simbad_query_sha256 = (
        trusted.simbad_query_sha256
        if trusted is not None
        else hashlib.sha256(
            producer_control_population._simbad_query_text().encode("utf-8")
        ).hexdigest()
    )
    simbad_rows = exclusions[exclusions["exclusion_catalog"] == "SIMBAD"]
    bp_ids = set(bp_rp["gaia_dr3_source_id"].astype(int))
    if not set(exclusions["gaia_dr3_source_id"].astype(int)).issubset(bp_ids):
        raise ValueError("external exclusion names a non-surviving parent source")
    for index, trace in enumerate(simbad_traces):
        chunk = bp_rp.iloc[
            index
            * validation.MAX_NETWORK_SOURCE_CHUNK : (index + 1)
            * validation.MAX_NETWORK_SOURCE_CHUNK
        ]
        input_frame = chunk.loc[:, ["gaia_dr3_source_id", "ra", "dec"]].copy()
        expected_input_sha256 = sha256_frame(input_frame)
        if trace["query_sha256"] != simbad_query_sha256:
            raise ValueError("SIMBAD provenance query does not match registered query")
        if trace["input_sha256"] != expected_input_sha256:
            raise ValueError("SIMBAD provenance input chunks are missing or reordered")
        raw_rows = int(trace["response_rows"])
        if raw_rows > len(chunk) * validation.MAX_MATCHES_PER_SOURCE_CATALOG:
            raise ValueError("SIMBAD provenance response exceeds the chunk bound")
        chunk_ids = set(chunk["gaia_dr3_source_id"].astype(int))
        normalized_rows = int(simbad_rows["gaia_dr3_source_id"].astype(int).isin(chunk_ids).sum())
        if raw_rows < normalized_rows or (raw_rows == 0) != (normalized_rows == 0):
            raise ValueError("SIMBAD raw/normalized response counts are inconsistent")
    simbad_raw_total = sum(int(trace["response_rows"]) for trace in simbad_traces)
    if trusted is not None and (
        simbad_raw_total != trusted.simbad_raw_response_rows
        or len(simbad_rows) != trusted.simbad_normalized_rows
    ):
        raise ValueError("trusted SIMBAD raw/normalized counts do not match release identity")

    if trusted is not None:
        chen_query_sha256 = trusted.chen_query_sha256
    else:
        chen_descriptor = (
            f"Vizier:{producer_control_population.CHEN_CATALOG}:"
            f"columns=Name,_RA,_DE:row_limit={validation.MAX_CLI_SOURCE_IDS}"
        )
        chen_query_sha256 = hashlib.sha256(chen_descriptor.encode("utf-8")).hexdigest()
    if (
        chen_trace["query_sha256"] != chen_query_sha256
        or chen_trace["input_sha256"] != chen_query_sha256
    ):
        raise ValueError("Chen provenance query/input does not match registered catalog")
    chen_response_rows = int(chen_trace["response_rows"])
    if not 0 <= chen_response_rows < validation.MAX_CLI_SOURCE_IDS:
        raise ValueError("Chen provenance response row count is outside the catalog bound")
    chen_rows = exclusions[exclusions["exclusion_catalog"] == "Chen2014"]
    if len(chen_rows) > 0 and chen_response_rows == 0:
        raise ValueError("Chen raw/normalized response counts are inconsistent")
    if trusted is not None and (
        chen_response_rows != trusted.chen_response_rows
        or len(chen_rows) != trusted.chen_normalized_rows
    ):
        raise ValueError("trusted Chen raw/normalized counts do not match release identity")


def _load_control_artifact(
    manifest_path: Path,
    *,
    release_id: str | None,
    review_only: bool,
) -> tuple[pd.DataFrame, Path, TrustedFinalRelease | None]:
    root = manifest_path.parent
    if not root.exists() or root.is_symlink():
        raise FileNotFoundError("safe control release directory not found")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"conformant control manifest not found: {manifest_path.name}")
    payload, manifest_sha256 = _read_bounded_yaml_with_sha256(manifest_path, root=root)
    manifest = validate_control_manifest(payload)
    if review_only:
        if release_id is not None:
            raise ValueError("review-only validation must not name a release identity")
        trusted = None
        if dict(manifest["software"]) != software_provenance():
            raise ValueError("candidate software provenance does not match review runtime")
    else:
        if release_id is None:
            raise ValueError("scientific loading requires an explicit release identity")
        trusted = _trusted_final_release(release_id, manifest, manifest_sha256)
        if trusted is None:
            raise ValueError("manifest bytes are not authorized for the release identity")
    prereg_path = repository_root() / PREREGISTRATION_RELATIVE_PATH
    if sha256_file(prereg_path) != PREREGISTRATION_SHA256:
        raise ValueError("frozen pre-registration bytes do not match release binding")
    raw_descriptor = manifest["artifacts"]["raw_candidates"]
    control_descriptor = manifest["artifacts"]["controls"]
    exclusion_descriptor = manifest["artifacts"]["exclusions"]
    raw_path = _safe_contained_path(root, raw_descriptor["path"], must_exist=True)
    control_path = _safe_contained_path(root, control_descriptor["path"], must_exist=True)
    exclusion_path = _safe_contained_path(root, exclusion_descriptor["path"], must_exist=True)
    raw_candidates = _read_verified_parquet(
        raw_path,
        root=root,
        maximum_rows=validation.MAX_RAW_CONTROL_ROWS,
        descriptor=raw_descriptor,
    )
    controls = _read_verified_parquet(
        control_path,
        root=root,
        maximum_rows=validation.MAX_FINAL_CONTROL_ROWS,
        descriptor=control_descriptor,
    )
    exclusions = _read_verified_parquet(
        exclusion_path,
        root=root,
        maximum_rows=validation.MAX_EXCLUSION_ROWS,
        descriptor=exclusion_descriptor,
    )
    validation.validate_joined_source_frame(
        raw_candidates, maximum_rows=validation.MAX_RAW_CONTROL_ROWS
    )
    if sha256_frame(raw_candidates) != manifest["raw_input_provenance"]["content_sha256"]:
        raise ValueError("released raw candidate content does not match raw input provenance")
    validation.validate_control_artifact(controls, minimum_rows=MIN_CONTROL_ROWS)
    validation.validate_exclusions(exclusions)
    validation.validate_control_derivation(raw_candidates, controls, exclusions)
    _validate_release_query_provenance(
        manifest,
        raw_candidates,
        exclusions,
        trusted=trusted,
    )
    if trusted is not None:
        semantic_hashes = {
            "raw_candidates": (raw_candidates, trusted.raw_candidates.content_sha256),
            "controls": (controls, trusted.controls.content_sha256),
            "exclusions": (exclusions, trusted.exclusions.content_sha256),
        }
        for name, (frame, expected) in semantic_hashes.items():
            if sha256_frame(frame) != expected:
                raise ValueError(f"trusted {name} semantic content SHA-256 mismatch")
    actual_retained = _rows_by_stratum(controls, manifest["selection"]["strata"])
    if actual_retained != manifest["selection"]["retained_rows_by_stratum"]:
        raise ValueError("control rows do not match retained stratum provenance")
    excluded_ids = set(exclusions["gaia_dr3_source_id"].astype(int))
    control_ids = set(controls["gaia_dr3_source_id"].astype(int))
    if excluded_ids & control_ids:
        raise ValueError("excluded source identifier remains in control artifact")
    counts = manifest["filter_counts"]
    if len(excluded_ids) != counts["excluded_unique_sources"]:
        raise ValueError("exclusion source count does not match manifest")
    for catalog, field in (
        ("SIMBAD", "simbad_excluded_sources"),
        ("Chen2014", "chen_excluded_sources"),
    ):
        actual = exclusions.loc[
            exclusions["exclusion_catalog"] == catalog, "gaia_dr3_source_id"
        ].nunique()
        if int(actual) != counts[field]:
            raise ValueError(f"{catalog} exclusion count does not match manifest")
    return controls, control_path, trusted


def load_authorized_control_release(
    manifest_path: Path,
    *,
    release_id: str,
) -> AuthorizedControlRelease:
    """Load one exact registry-authorized release for scientific analysis."""
    controls, control_path, trusted = _load_control_artifact(
        manifest_path,
        release_id=release_id,
        review_only=False,
    )
    if trusted is None:  # defensive invariant: scientific loading always authorizes.
        raise ReleaseRegistryError("scientific release authorization was not retained")
    return AuthorizedControlRelease(
        release_id=release_id,
        manifest_path=manifest_path.resolve(),
        controls_path=control_path,
        controls_sha256=trusted.controls.sha256,
        controls_descriptor=trusted.controls,
        controls=controls,
    )


def load_control_artifact(manifest_path: Path, *, release_id: str) -> pd.DataFrame:
    """Load an exact registry-authorized release for scientific analysis.

    Structural validity and current-producer provenance are intentionally
    insufficient.  The caller must name one release identity in
    ``TRUSTED_FINAL_RELEASES``, and the manifest, artifacts, provenance traces,
    and semantic content must match that registry entry exactly.
    """
    return load_authorized_control_release(
        manifest_path,
        release_id=release_id,
    ).controls


def validate_control_release_candidate(manifest_path: Path) -> pd.DataFrame:
    """Review a current-producer candidate without authorizing analysis use.

    This API exists only for independent release review.  Model fitting,
    calibration, injection, FDR, and ranking code must call
    ``load_authorized_control_release`` with a registry identity instead.
    """
    controls, _, _ = _load_control_artifact(
        manifest_path,
        release_id=None,
        review_only=True,
    )
    return controls

"""Reproducible producer provenance for the frozen v0.1.4 instrument."""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import platform
import re
import ssl
import subprocess
import tarfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from pharos.control_artifacts_v014 import ArtifactIdentity, sha256_bytes, sha256_file
from pharos.control_population_v014 import (
    BP_RP_SCHEMA,
    CHEN_RAW_SCHEMA,
    EXCLUSION_SCHEMA,
    FINAL_SCHEMA,
    GAIA_DECODED_SCHEMA,
    GAIA_NORMALIZED_SCHEMA,
    PREREGISTRATION_SHA256,
    RAW_SCHEMA,
    SIMBAD_RAW_SCHEMA,
)

CA_BUNDLE_BYTES: Final = 234_072
CA_BUNDLE_SHA256: Final = "d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453"
EXPECTED_TOOLCHAIN: Final = {
    "python_implementation": "CPython",
    "python_version": "3.14.6",
    "uv_version": "0.11.12",
    "os_name": "macOS",
    "os_version": "27.0",
    "os_build": "26A5388g",
    "kernel_release": "27.0.0",
    "architecture": "arm64",
    "openssl_version": "OpenSSL 3.6.3 9 Jun 2026",
    "pandas_version": "3.0.5",
    "pyarrow_version": "25.0.0",
    "numpy_version": "2.5.1",
    "pyyaml_version": "6.0.3",
    "astropy_version": "8.0.1",
    "astroquery_version": "0.4.11",
    "certifi_version": "2026.10.18",
}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProducerIdentity:
    git_commit: str
    source_tree_sha256: str
    uv_lock_sha256: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git(*arguments: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root(),
        check=True,
        capture_output=True,
        text=text,
        timeout=30,
    )
    return result.stdout


def require_clean_producer_tree() -> None:
    dirty = _git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "src/pharos",
        "pyproject.toml",
        "uv.lock",
    )
    if dirty:
        raise RuntimeError("producer source/config/lock tree is dirty")


def _indexed_source_paths(commit: str) -> tuple[str, ...]:
    output = _git("ls-tree", "-r", "--name-only", commit, "--", "src/pharos")
    paths = [line for line in str(output).splitlines() if line]
    paths.append("pyproject.toml")
    encoded = sorted(paths, key=lambda value: value.encode("utf-8"))
    if len(encoded) != len(set(encoded)) or not encoded:
        raise RuntimeError("producer source-tree member set is invalid")
    for path in encoded:
        kind = str(_git("cat-file", "-t", f"{commit}:{path}")).strip()
        if kind != "blob":
            raise RuntimeError("source tree contains a non-regular indexed member")
    return tuple(encoded)


def _blob(commit: str, path: str) -> bytes:
    value = _git("show", f"{commit}:{path}", text=False)
    assert isinstance(value, bytes)
    return value


def source_tree_sha256(commit: str) -> str:
    if _HEX40.fullmatch(commit) is None:
        raise ValueError("producer commit must be full lowercase hex")
    digest = hashlib.sha256(b"pharos-source-tree-v1\x00")
    for path in _indexed_source_paths(commit):
        data = _blob(commit, path)
        name = path.encode("utf-8")
        digest.update(len(name).to_bytes(8, "little"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "little"))
        digest.update(data)
    return digest.hexdigest()


def producer_identity() -> ProducerIdentity:
    require_clean_producer_tree()
    commit = str(_git("rev-parse", "HEAD")).strip()
    lock_path = repository_root() / "uv.lock"
    if not lock_path.is_file() or lock_path.is_symlink():
        raise RuntimeError("uv.lock is missing or is a symlink")
    return ProducerIdentity(commit, source_tree_sha256(commit), sha256_file(lock_path))


def canonical_json(value: object) -> bytes:
    """RFC-8785 canonical form for the string/int/bool/null objects used here."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def build_metadata(identity: ProducerIdentity) -> bytes:
    data = tomllib.loads(_blob(identity.git_commit, "pyproject.toml").decode("utf-8"))
    project = data["project"]
    payload = {
        "build_backend": "setuptools.build_meta",
        "build_requirements": ["setuptools==83.0.0", "wheel==0.47.0"],
        "producer_git_commit": identity.git_commit,
        "project_name": project["name"],
        "project_version": project["version"],
        "schema_version": "pharos.build-metadata.v1",
        "source_tree_sha256": identity.source_tree_sha256,
        "uv_lock_sha256": identity.uv_lock_sha256,
    }
    return canonical_json(payload)


def source_members(identity: ProducerIdentity, members: dict[str, tuple[bytes, str]]) -> bytes:
    payload = {
        "members": [
            {
                "byte_sha256": sha256_bytes(data),
                "bytes": len(data),
                "path": path,
                "role": role,
            }
            for path, (data, role) in sorted(members.items(), key=lambda item: item[0].encode())
        ],
        "schema_version": "pharos.source-members.v1",
        "source_tree_algorithm": "pharos-source-tree-v1",
        "source_tree_sha256": identity.source_tree_sha256,
    }
    return canonical_json(payload)


def source_distribution(identity: ProducerIdentity) -> bytes:
    members: dict[str, tuple[bytes, str]] = {}
    for path in _indexed_source_paths(identity.git_commit):
        role = "build_config" if path == "pyproject.toml" else "source"
        members[path] = (_blob(identity.git_commit, path), role)
    members["BUILD-METADATA.json"] = (build_metadata(identity), "build_metadata")
    members["SOURCE-MEMBERS.json"] = (source_members(identity, members), "build_metadata")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path in sorted(members, key=lambda value: value.encode("utf-8")):
            data = members[path][0]
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    raw = output.getvalue()
    # tarfile pads to a 10 KiB record. The registration requires exactly two
    # zero end blocks, so remove only post-terminator all-zero records.
    last_nonzero = len(raw.rstrip(b"\x00"))
    aligned = ((last_nonzero + 511) // 512) * 512
    result = raw[:aligned] + b"\x00" * 1024
    if len(result) % 512 or result[-1024:] != b"\x00" * 1024:
        raise AssertionError("source distribution is not exact ustar termination")
    with tarfile.open(fileobj=io.BytesIO(result), mode="r:") as archive:
        names = archive.getnames()
        if names != sorted(members, key=lambda value: value.encode("utf-8")):
            raise AssertionError("source distribution member order drifted")
        if any(member.issym() or member.islnk() or not member.isfile() for member in archive):
            raise AssertionError("source distribution contains non-regular members")
    return result


def validate_ca_bundle(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("registered CA bundle is missing or not a regular file")
    data = path.read_bytes()
    if len(data) != CA_BUNDLE_BYTES or sha256_bytes(data) != CA_BUNDLE_SHA256:
        raise RuntimeError("installed CA bundle does not match the registered immutable input")
    return data


def _shared_cache_uuid() -> str:
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "_dyld_get_shared_cache_uuid", None)
    if function is None:
        raise RuntimeError("dyld shared-cache UUID API unavailable")
    value = (ctypes.c_ubyte * 16)()
    function.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
    function.restype = ctypes.c_bool
    if not function(value):
        raise RuntimeError("running signed dyld cache has no readable UUID")
    return str(uuid.UUID(bytes=bytes(value)))


def toolchain_record(*, ca_bundle_path: Path) -> dict[str, object]:
    """Return the exact registered release-platform record or fail closed."""
    import astropy
    import astroquery
    import certifi
    import numpy
    import pandas
    import pyarrow

    validate_ca_bundle(ca_bundle_path)
    uv_output = subprocess.run(
        ["uv", "--version"], check=True, capture_output=True, text=True, timeout=10
    ).stdout.split()[1]
    os_build = subprocess.run(
        ["sw_vers", "-buildVersion"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    observed = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "uv_version": uv_output,
        "os_name": "macOS" if platform.system() == "Darwin" else platform.system(),
        "os_version": platform.mac_ver()[0],
        "os_build": os_build,
        "kernel_release": platform.release(),
        "architecture": platform.machine(),
        "openssl_version": ssl.OPENSSL_VERSION,
        "pandas_version": pandas.__version__,
        "pyarrow_version": pyarrow.__version__,
        "numpy_version": numpy.__version__,
        "pyyaml_version": yaml.__version__,
        "astropy_version": astropy.__version__,
        "astroquery_version": astroquery.__version__,
        "certifi_version": certifi.__version__,
    }
    differences = {
        key: (EXPECTED_TOOLCHAIN[key], value)
        for key, value in observed.items()
        if EXPECTED_TOOLCHAIN[key] != value
    }
    if differences:
        raise RuntimeError(
            f"runtime does not match registered release platform: {sorted(differences)}"
        )
    return {
        "schema_version": "pharos.toolchain.v1",
        "python_implementation": observed["python_implementation"],
        "python_version": observed["python_version"],
        "uv_version": observed["uv_version"],
        "os_name": observed["os_name"],
        "os_version": observed["os_version"],
        "os_build": observed["os_build"],
        "kernel_release": observed["kernel_release"],
        "architecture": observed["architecture"],
        "openssl_version": observed["openssl_version"],
        "libc_math_runtime_identity": "libSystem.B.dylib@running-signed-dyld-shared-cache",
        "libc_math_runtime_sha256": None,
        "dyld_shared_cache_uuid": _shared_cache_uuid(),
        "pandas_version": observed["pandas_version"],
        "pyarrow_version": observed["pyarrow_version"],
        "numpy_version": observed["numpy_version"],
        "pyyaml_version": observed["pyyaml_version"],
        "astropy_version": observed["astropy_version"],
        "astroquery_version": observed["astroquery_version"],
        "certifi_version": observed["certifi_version"],
        "ca_bundle_bytes": CA_BUNDLE_BYTES,
        "ca_bundle_sha256": CA_BUNDLE_SHA256,
        "parquet_format_version": "2.6",
        "parquet_writer_profile": "pharos-parquet-v014",
    }


def normalizer_registry(identity: ProducerIdentity) -> list[dict[str, object]]:
    path = "src/pharos/control_population_v014.py"
    source_hash = sha256_bytes(_blob(identity.git_commit, path))
    tuples = (
        (
            0,
            "gaia-page-normalize-v014",
            "normalize_gaia_page",
            GAIA_DECODED_SCHEMA,
            GAIA_NORMALIZED_SCHEMA,
        ),
        (1, "bp-rp-derive-v014", "derive_bp_rp_survivors", RAW_SCHEMA, BP_RP_SCHEMA),
        (
            2,
            "simbad-local-exclusion-v014",
            "normalize_simbad_exclusions",
            SIMBAD_RAW_SCHEMA,
            EXCLUSION_SCHEMA,
        ),
        (
            3,
            "chen-local-exclusion-v014",
            "match_chen_exclusions",
            CHEN_RAW_SCHEMA,
            EXCLUSION_SCHEMA,
        ),
        (4, "final-difference-v014", "derive_quiet_negative", BP_RP_SCHEMA, FINAL_SCHEMA),
    )
    return [
        {
            "ordinal": ordinal,
            "normalization_id": normalization_id,
            "source_member_path": path,
            "callable_name": callable_name,
            "source_file_sha256": source_hash,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "parameter_binding_sha256": PREREGISTRATION_SHA256,
        }
        for ordinal, normalization_id, callable_name, input_schema, output_schema in tuples
    ]


def write_source_distribution(path: Path, identity: ProducerIdentity) -> ArtifactIdentity:
    data = source_distribution(identity)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    return ArtifactIdentity(
        path.name, sha256_bytes(data), None, len(data), None, "pharos.source-distribution.v1", None
    )

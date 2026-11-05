"""Separate review and authorized scientific loaders for v0.1.4.

Review mode can inspect an unregistered candidate only under the identical
clean producer tree.  Scientific loading has no review-mode escape hatch and
requires an exact external registry entry plus Git review chain.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from pharos import trusted_control_releases_v014 as registry
from pharos.control_artifacts_v014 import sha256_file, validate_relative_path
from pharos.control_manifests_v014 import (
    strict_yaml_load,
    validate_checkpoint_manifest,
    validate_final_manifest,
    validate_review_attestation,
)
from pharos.control_population_v014 import (
    INCORPORATED_PREREGISTRATION_BYTES,
    INCORPORATED_PREREGISTRATION_SHA256S,
    PREREGISTRATION_BYTES,
    PREREGISTRATION_SHA256,
)
from pharos.control_provenance_v014 import producer_identity

REGISTRY_FIELDS: Final = (
    "entry_id",
    "role",
    "attempt_id",
    "candidate_commit",
    "manifest_path",
    "manifest_byte_sha256",
    "pre_registration_byte_sha256",
    "producer",
    "raw_checkpoint_entry_id",
    "artifact_identities",
    "request_index_byte_sha256",
    "request_index_semantic_sha256",
    "transport_attempts_byte_sha256",
    "transport_attempts_semantic_sha256",
    "pass_report_byte_sha256",
    "review_attestation_path",
    "review_attestation_byte_sha256",
    "review_evidence_commit",
    "registry_parent_commit",
)
_HEX = set("0123456789abcdef")


@dataclass(frozen=True)
class LoadedCandidate:
    root: Path
    manifest: Mapping[str, object]
    manifest_sha256: str
    trusted: bool
    registry_entry_id: str | None


def _hex(value: object, size: int, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != size
        or any(character not in _HEX for character in value)
    ):
        raise ValueError(f"registry {name} is not lowercase hex{size}")
    return value


def _entry(value: object, expected_role: str) -> dict[str, object]:
    if type(value) is not tuple or len(value) != len(REGISTRY_FIELDS):
        raise ValueError("registry entry is not an exact immutable tuple")
    record = dict(zip(REGISTRY_FIELDS, value, strict=True))
    if type(record["entry_id"]) is not str or not 1 <= len(record["entry_id"].encode()) <= 128:
        raise ValueError("registry entry_id invalid")
    if record["role"] != expected_role:
        raise ValueError("registry role/list mismatch")
    _hex(record["candidate_commit"], 40, "candidate commit")
    _hex(record["manifest_byte_sha256"], 64, "manifest hash")
    if record["pre_registration_byte_sha256"] != PREREGISTRATION_SHA256:
        raise ValueError("registry pre-registration hash mismatch")
    validate_relative_path(str(record["manifest_path"]))
    artifacts = record["artifact_identities"]
    if type(artifacts) is not tuple or not artifacts:
        raise ValueError("registry artifact identities must be a non-empty tuple")
    for artifact in artifacts:
        if type(artifact) is not tuple or len(artifact) != 7:
            raise ValueError("registry artifact identity schema mismatch")
        validate_relative_path(str(artifact[0]))
        _hex(artifact[1], 64, "artifact hash")
        if artifact[2] is not None:
            _hex(artifact[2], 64, "artifact semantic hash")
        if type(artifact[3]) is not int or artifact[3] < 0:
            raise ValueError("registry artifact byte count invalid")
    for name in (
        "request_index_byte_sha256",
        "request_index_semantic_sha256",
        "transport_attempts_byte_sha256",
        "transport_attempts_semantic_sha256",
        "review_attestation_byte_sha256",
    ):
        _hex(record[name], 64, name)
    if expected_role == "raw_checkpoint":
        if (
            record["raw_checkpoint_entry_id"] is not None
            or record["pass_report_byte_sha256"] is not None
        ):
            raise ValueError("raw checkpoint contains final-only registry fields")
    else:
        if type(record["raw_checkpoint_entry_id"]) is not str:
            raise ValueError("final release has no raw checkpoint reference")
        _hex(record["pass_report_byte_sha256"], 64, "pass report hash")
    _hex(record["review_evidence_commit"], 40, "review evidence commit")
    _hex(record["registry_parent_commit"], 40, "registry parent commit")
    if record["review_evidence_commit"] != record["registry_parent_commit"]:
        raise ValueError("registry parent is not review evidence commit")
    return record


def validated_registry() -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    keys = registry.AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256
    raw = registry.TRUSTED_RAW_CHECKPOINTS
    final = registry.TRUSTED_FINAL_RELEASES
    if type(keys) is not tuple or type(raw) is not tuple or type(final) is not tuple:
        raise ValueError("v0.1.4 trust roots must be immutable tuples")
    if len(keys) != len(set(keys)):
        raise ValueError("authorized reviewer key hashes duplicate")
    for value in keys:
        _hex(value, 64, "authorized reviewer key")
    raw_entries = tuple(_entry(value, "raw_checkpoint") for value in raw)
    final_entries = tuple(_entry(value, "final_release") for value in final)
    ids = [str(item["entry_id"]) for item in (*raw_entries, *final_entries)]
    if len(ids) != len(set(ids)):
        raise ValueError("registry entry IDs duplicate")
    if not keys and (raw_entries or final_entries):
        raise PermissionError("registry has entries but the reviewer trust root is empty")
    raw_ids = {str(item["entry_id"]) for item in raw_entries}
    if any(str(item["raw_checkpoint_entry_id"]) not in raw_ids for item in final_entries):
        raise ValueError("final registry entry references an unknown raw checkpoint")
    return raw_entries, final_entries


def _open_contained(root: Path, relative: str) -> tuple[int, os.stat_result]:
    path = validate_relative_path(relative)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    current = root_fd
    try:
        for part in path.parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            if current != root_fd:
                os.close(current)
            current = child
        fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            os.close(fd)
            raise ValueError("candidate artifact is not a private regular file")
        return fd, opened
    finally:
        if current != root_fd:
            os.close(current)
        os.close(root_fd)


def _hash_contained(root: Path, relative: str) -> tuple[str, int]:
    fd, opened = _open_contained(root, relative)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        # fd is closed by fdopen on the success path.
        pass
    return digest.hexdigest(), opened.st_size


def _verify_packaged_prereg(root: Path, manifest: Mapping[str, object]) -> None:
    relative = str(manifest["pre_registration_path"])
    digest, size = _hash_contained(root, relative)
    if digest != PREREGISTRATION_SHA256 or size != PREREGISTRATION_BYTES:
        raise ValueError("packaged pre-registration is not byte-identical to frozen input")
    entries = manifest["incorporated_pre_registrations"]
    if not isinstance(entries, list) or len(entries) != len(
        INCORPORATED_PREREGISTRATION_SHA256S
    ):
        raise ValueError("manifest must incorporate every frozen predecessor")
    for entry, digest, size in zip(
        entries, INCORPORATED_PREREGISTRATION_SHA256S, INCORPORATED_PREREGISTRATION_BYTES, strict=True
    ):
        path = str(entry["path"])
        found_digest, found_size = _hash_contained(root, path)
        if found_digest != digest or found_size != size:
            raise ValueError("packaged incorporated pre-registration is not byte-identical")


def _verify_raw_reference_against_checkpoint(
    repository: Path, manifest: Mapping[str, object], entry: Mapping[str, object]
) -> None:
    """Frozen v0.1.4 Section 5.1 loader cross-check: the final manifest's
    RawProducerReference must match the registered raw checkpoint."""
    raw_entry_id = entry.get("raw_checkpoint_entry_id")
    if not isinstance(raw_entry_id, str):
        raise ValueError("final release entry does not name its raw checkpoint")
    reference = cast(Mapping[str, object], manifest["raw_producer"])
    if reference["raw_checkpoint_registry_entry_id"] != raw_entry_id:
        raise ValueError("raw producer reference names a different checkpoint entry")
    raw, _ = validated_registry()
    matches = [candidate for candidate in raw if candidate["entry_id"] == raw_entry_id]
    if len(matches) != 1:
        raise PermissionError("referenced raw checkpoint is not exactly registered")
    raw_manifest_path = repository / str(matches[0]["manifest_path"])
    if sha256_file(raw_manifest_path) != reference["raw_checkpoint_manifest_byte_sha256"]:
        raise ValueError("raw producer reference manifest hash mismatch")
    raw_manifest = strict_yaml_load(raw_manifest_path)
    validate_checkpoint_manifest(raw_manifest)
    raw_producer = cast(Mapping[str, object], raw_manifest["raw_producer"])
    for key in ("git_commit", "source_tree_sha256", "uv_lock_sha256", "toolchain_sha256"):
        if raw_producer[key] != reference[key]:
            raise ValueError(f"raw producer reference {key} mismatch")


def _verify_registered_artifacts(root: Path, entry: Mapping[str, object]) -> None:
    """Verify every registered payload through the contained no-follow reader."""
    for artifact in cast(tuple[tuple[object, ...], ...], entry["artifact_identities"]):
        digest, size = _hash_contained(root, str(artifact[0]))
        if digest != artifact[1] or size != artifact[3]:
            raise ValueError("registered artifact identity mismatch")


def load_candidate_for_review(root: Path) -> LoadedCandidate:
    """Load a candidate for read-only review under its identical producer tree."""
    root = root.resolve(strict=True)
    manifest_path = root / (
        "checkpoint_manifest.yaml"
        if (root / "checkpoint_manifest.yaml").is_file()
        else "manifest.yaml"
    )
    manifest = strict_yaml_load(manifest_path)
    if manifest_path.name == "checkpoint_manifest.yaml":
        validate_checkpoint_manifest(manifest)
        producer = manifest["raw_producer"]
    else:
        validate_final_manifest(manifest)
        producer = manifest["release_producer"]
    assert isinstance(producer, Mapping)
    current = producer_identity()
    if (
        producer["git_commit"] != current.git_commit
        or producer["source_tree_sha256"] != current.source_tree_sha256
        or producer["uv_lock_sha256"] != current.uv_lock_sha256
    ):
        raise PermissionError("review mode requires the identical clean producer tree")
    _verify_packaged_prereg(root, manifest)
    return LoadedCandidate(root, manifest, sha256_file(manifest_path), False, None)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _verify_review_chain(repo: Path, entry: Mapping[str, object]) -> None:
    candidate = str(entry["candidate_commit"])
    review = str(entry["review_evidence_commit"])
    parents = _git(repo, "show", "-s", "--format=%P", review).split()
    if not parents or parents[0] != candidate:
        raise PermissionError("review evidence is not a direct child of candidate commit")
    status = _git(repo, "verify-commit", review)
    if status is None:  # pragma: no cover - subprocess always returns text
        raise PermissionError("review commit signature verification failed")
    changed = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", review).splitlines()
    if changed != [entry["review_attestation_path"]]:
        raise PermissionError("review commit changes more than its one attestation")


def load_registered_final_release(entry_id: str, repository: Path) -> LoadedCandidate:
    """Scientific loader: exact registry only, with no review-mode fallback."""
    _, final = validated_registry()
    matches = [entry for entry in final if entry["entry_id"] == entry_id]
    if len(matches) != 1:
        raise PermissionError("final release is not exactly authorized")
    entry = matches[0]
    repository = repository.resolve(strict=True)
    _verify_review_chain(repository, entry)
    manifest_path = repository / str(entry["manifest_path"])
    if sha256_file(manifest_path) != entry["manifest_byte_sha256"]:
        raise ValueError("registered manifest byte hash mismatch")
    manifest = strict_yaml_load(manifest_path)
    validate_final_manifest(manifest)
    root = manifest_path.parent
    _verify_raw_reference_against_checkpoint(repository, manifest, entry)
    _verify_packaged_prereg(root, manifest)
    _verify_registered_artifacts(root, entry)
    attestation_path = repository / str(entry["review_attestation_path"])
    if sha256_file(attestation_path) != entry["review_attestation_byte_sha256"]:
        raise ValueError("review attestation byte hash mismatch")
    attestation = strict_yaml_load(attestation_path)
    validate_review_attestation(attestation, registry.AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256)
    return LoadedCandidate(root, manifest, str(entry["manifest_byte_sha256"]), True, entry_id)


def load_registered_raw_checkpoint(entry_id: str, repository: Path) -> LoadedCandidate:
    """Release-worker loader: exact registered Gaia checkpoint only."""
    raw, _ = validated_registry()
    matches = [entry for entry in raw if entry["entry_id"] == entry_id]
    if len(matches) != 1:
        raise PermissionError("raw checkpoint is not exactly authorized")
    entry = matches[0]
    repository = repository.resolve(strict=True)
    _verify_review_chain(repository, entry)
    manifest_path = repository / str(entry["manifest_path"])
    if sha256_file(manifest_path) != entry["manifest_byte_sha256"]:
        raise ValueError("registered checkpoint manifest hash mismatch")
    manifest = strict_yaml_load(manifest_path)
    validate_checkpoint_manifest(manifest)
    root = manifest_path.parent
    _verify_packaged_prereg(root, manifest)
    _verify_registered_artifacts(root, entry)
    return LoadedCandidate(root, manifest, str(entry["manifest_byte_sha256"]), True, entry_id)

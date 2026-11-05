"""Strict state, YAML, manifest, pass-report, and review schemas for v0.1.4."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypeAlias

import yaml

from pharos.control_artifacts_v014 import validate_relative_path
from pharos.control_population_v014 import (
    INCORPORATED_PREREGISTRATION_SHA256S,
    PREREGISTRATION_BYTES,
    PREREGISTRATION_SHA256,
)
from pharos.control_provenance_v014 import canonical_json

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

MAX_YAML_BYTES: Final = 1_048_576
MAX_TEXT_SCALAR_BYTES: Final = 4_096
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")

SCHEMA_VERSIONS: Final = frozenset(
    {
        "pharos.gaia-decoded-page.v0.1.4",
        "pharos.gaia-normalized-page.v0.1.4",
        "pharos.quiet-negative-raw.v0.1.4",
        "pharos.quiet-negative-bp-rp.v0.1.4",
        "pharos.simbad-upload.v0.1.4",
        "pharos.simbad-decoded-raw.v0.1.4",
        "pharos.chen-decoded-raw.v0.1.4",
        "pharos.quiet-negative-exclusions.v0.1.4",
        "pharos.quiet-negative.v0.1.4",
        "pharos.remote-request-index.v0.1.4",
        "pharos.remote-transport-attempts.v0.1.4",
        "pharos.attempt-state.v0.1.4",
        "pharos.quiet-negative-checkpoint-manifest.v0.1.4",
        "pharos.quiet-negative-manifest.v0.1.4",
        "pharos.quiet-negative-pass-report.v0.1.4",
        "pharos.control-review-attestation.v0.1.4",
    }
)

LIMITS_ITEMS: Final = (
    ("source_batch_rows", 500),
    ("simbad_matches_per_source_catalog", 100),
    ("simbad_maxrec", 50001),
    ("chen_rows_exclusive_max", 10000),
    ("cli_source_ids_max", 10000),
    ("raw_candidate_rows_max", 250000),
    ("final_control_rows_min", 50000),
    ("final_control_rows_max", 250000),
    ("exclusion_rows_max", 5000000),
    ("wire_bytes_max", 33554432),
    ("decompressed_response_bytes_max", 67108864),
    ("deep_table_bytes_max", 134217728),
    ("live_response_table_bytes_max", 268435456),
    ("process_rss_bytes_max", 1073741824),
    ("yaml_bytes_max", 1048576),
    ("parquet_file_bytes_max", 2147483648),
    ("parquet_footer_bytes_max", 16777216),
    ("parquet_metadata_bytes_max", 1048576),
    ("parquet_columns_max", 64),
    ("parquet_row_groups_max", 1024),
    ("parquet_nesting_depth_max", 0),
    ("parquet_column_chunk_compressed_bytes_max", 67108864),
    ("parquet_column_chunk_uncompressed_bytes_max", 134217728),
    ("parquet_data_page_compressed_bytes_max", 16777216),
    ("parquet_data_page_uncompressed_bytes_max", 33554432),
    ("parquet_page_header_bytes_max", 65536),
    ("parser_allocator_bytes_max", 268435456),
    ("parser_address_space_bytes_max", 1073741824),
    ("text_scalar_bytes_max", 4096),
    ("catalog_text_bytes_max", 512),
    ("query_bytes_max", 65536),
    ("decoded_string_bytes_max", 33554432),
    ("release_files_max", 2048),
    ("release_tree_bytes_max", 4294967296),
    ("relative_path_bytes_max", 240),
    ("filename_component_bytes_max", 180),
    ("logical_catalog_requests_max", 231),
    ("tcp_connect_timeout_seconds", 10),
    ("tls_handshake_timeout_seconds", 10),
    ("response_header_timeout_seconds", 60),
    ("body_read_timeout_seconds", 600),
    ("gaia_logical_deadline_seconds", 7200),
    ("gaia_poll_interval_seconds", 10),
    ("gaia_poll_operations_max", 720),
    ("simbad_logical_deadline_seconds", 600),
    ("chen_logical_deadline_seconds", 600),
    ("transport_attempts_max", 3),
    ("retry_wait_1_seconds", 5),
    ("retry_wait_2_seconds", 15),
    ("redirects_max", 0),
    ("peer_port", 443),
    ("ca_bundle_bytes", 234072),
    ("tls_version", "TLSv1.3"),
    ("ca_bundle_sha256", "d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453"),
    ("allowed_hostnames", ["gea.esac.esa.int", "simbad.cds.unistra.fr", "vizier.cds.unistra.fr"]),
)

ARTIFACT_KEYS: Final = (
    "path",
    "byte_sha256",
    "semantic_sha256",
    "bytes",
    "rows",
    "schema_version",
    "columns",
    "producer_role",
)
PRODUCER_KEYS: Final = (
    "git_commit",
    "source_tree_sha256",
    "uv_lock_sha256",
    "toolchain_sha256",
    "source_distribution",
)
# Frozen v0.1.4 Section 5.1: the final manifest's raw producer is bound by
# registered-checkpoint reference, not by an embedded source distribution.
RAW_REFERENCE_KEYS: Final = (
    "git_commit",
    "source_tree_sha256",
    "uv_lock_sha256",
    "toolchain_sha256",
    "raw_checkpoint_registry_entry_id",
    "raw_checkpoint_manifest_path",
    "raw_checkpoint_manifest_byte_sha256",
)
CHECKPOINT_KEYS: Final = (
    "schema_version",
    "status",
    "attempt_id",
    "state",
    "pre_registration_path",
    "pre_registration_byte_sha256",
    "pre_registration_bytes",
    "incorporated_pre_registrations",
    "created_at_utc",
    "raw_producer",
    "catalog_releases",
    "selection",
    "gaia_logical_requests",
    "transport_attempt_count",
    "artifacts",
    "request_order_rows_semantic_sha256",
    "canonical_parent_rows_semantic_sha256",
    "limits",
)
FINAL_KEYS: Final = (
    "schema_version",
    "status",
    "attempt_id",
    "state",
    "pre_registration_path",
    "pre_registration_byte_sha256",
    "pre_registration_bytes",
    "incorporated_pre_registrations",
    "created_at_utc",
    "raw_checkpoint_manifest_path",
    "raw_checkpoint_manifest_byte_sha256",
    "raw_checkpoint_registry_entry_id",
    "raw_checkpoint_candidate_commit",
    "raw_checkpoint_review_evidence_commit",
    "raw_producer",
    "release_producer",
    "catalog_releases",
    "selection",
    "gaia_logical_requests",
    "simbad_logical_requests",
    "chen_logical_requests",
    "total_logical_requests",
    "transport_attempt_count",
    "raw_rows",
    "bp_rp_rows",
    "simbad_raw_rows",
    "simbad_normalized_rows",
    "simbad_unique_sources",
    "chen_raw_rows",
    "chen_normalized_rows",
    "chen_unique_sources",
    "exclusion_rows",
    "excluded_unique_sources",
    "final_rows",
    "artifacts",
    "request_order_rows_semantic_sha256",
    "canonical_parent_rows_semantic_sha256",
    "bp_rp_rows_semantic_sha256",
    "exclusions_semantic_sha256",
    "final_rows_semantic_sha256",
    "bp_rp_algorithm_id",
    "simbad_normalization_id",
    "chen_match_id",
    "final_difference_id",
    "limits",
)
PASS_REPORT_KEYS: Final = (
    "schema_version",
    "attempt_id",
    "pre_registration_sha256",
    "raw_checkpoint_manifest_sha256",
    "generated_at_utc",
    "producer",
    "gates",
    "all_passed",
    "test_results",
    "no_model_fit_attestation",
)
REVIEW_KEYS: Final = (
    "schema_version",
    "review_role",
    "attempt_id",
    "candidate_commit",
    "candidate_manifest_path",
    "candidate_manifest_byte_sha256",
    "pre_registration_byte_sha256",
    "reviewer_identity",
    "reviewer_signing_key_sha256",
    "reviewed_at_utc",
    "artifact_identities",
    "checks",
    "outcome",
    "notes",
)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


def _construct_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if type(key) is not str:
            raise ValueError("YAML mapping keys must be strings")
        if key in result:
            raise ValueError("duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def strict_yaml_load_bytes(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_YAML_BYTES:
        raise ValueError("YAML exceeds registered byte bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("YAML is not UTF-8") from exc
    for event in yaml.parse(text):
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML aliases and anchors are forbidden")
        tag = getattr(event, "tag", None)
        if tag is not None and not str(tag).startswith("tag:yaml.org,2002:"):
            raise ValueError("custom YAML tags are forbidden")
    payload = yaml.load(text, Loader=_UniqueKeyLoader)
    if type(payload) is not dict:
        raise TypeError("YAML document must be a mapping")
    _validate_scalar_bounds(payload)
    return payload


def _validate_scalar_bounds(value: object) -> None:
    if isinstance(value, str):
        if "\x00" in value or len(value.encode("utf-8")) > MAX_TEXT_SCALAR_BYTES:
            raise ValueError("YAML text scalar violates registered bound")
    elif type(value) is list:
        for item in value:
            _validate_scalar_bounds(item)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("YAML mapping key is not string")
            _validate_scalar_bounds(key)
            _validate_scalar_bounds(item)
    elif value is not None and type(value) not in (bool, int, float):
        raise TypeError("YAML value is not JSON-compatible")


def strict_yaml_load(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not os.path.isfile(path) or opened.st_size > MAX_YAML_BYTES:
            raise ValueError("YAML input is not a bounded regular file")
        raw = os.read(fd, MAX_YAML_BYTES + 1)
    finally:
        os.close(fd)
    return strict_yaml_load_bytes(raw)


def strict_yaml_dump(value: Mapping[str, object]) -> bytes:
    """Emit alias-free ordered YAML and validate the emitted bytes immediately."""
    text = yaml.dump(
        dict(value),
        Dumper=_NoAliasDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    raw = text.encode("utf-8")
    strict_yaml_load_bytes(raw)
    return raw


def _ordered(value: object, keys: Sequence[str], context: str) -> Mapping[str, object]:
    if type(value) is not dict or tuple(value) != tuple(keys):
        raise ValueError(f"{context} has missing, extra, or reordered keys")
    return value


def _hex(value: object, length: int, context: str) -> str:
    pattern = _HEX40 if length == 40 else _HEX64
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{context} must be lowercase hex{length}")
    return value


def _uuid4(value: object) -> str:
    if type(value) is not str:
        raise TypeError("attempt_id must be a string")
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("attempt_id must be lowercase canonical UUIDv4")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("timestamp must be RFC3339 UTC with six fractional digits")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return value


def _strict_int(value: object, context: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{context} must be an integer")
    return value


def timestamp_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_artifact_descriptor(value: object) -> Mapping[str, object]:
    record = _ordered(value, ARTIFACT_KEYS, "ArtifactDescriptor")
    validate_relative_path(str(record["path"]))
    _hex(record["byte_sha256"], 64, "artifact byte hash")
    if record["semantic_sha256"] is not None:
        _hex(record["semantic_sha256"], 64, "artifact semantic hash")
    for key in ("bytes",):
        if not 0 <= _strict_int(record[key], f"artifact {key}") <= 2_147_483_648:
            raise ValueError(f"artifact {key} outside registered bound")
    if record["rows"] is not None and _strict_int(record["rows"], "artifact rows") < 0:
        raise ValueError("artifact rows invalid")
    columns = record["columns"]
    if columns is not None and (
        type(columns) is not list
        or not 1 <= len(columns) <= 64
        or len(columns) != len(set(columns))
        or not all(type(item) is str and item for item in columns)
    ):
        raise ValueError("artifact columns invalid")
    if (record["rows"] is None) != (columns is None) or (record["semantic_sha256"] is None) != (
        columns is None
    ):
        raise ValueError("tabular artifact descriptor nullability is inconsistent")
    if record["producer_role"] not in ("raw", "release"):
        raise ValueError("artifact producer role invalid")
    return record


def validate_producer(value: object) -> Mapping[str, object]:
    record = _ordered(value, PRODUCER_KEYS, "ProducerRecord")
    _hex(record["git_commit"], 40, "producer commit")
    for key in ("source_tree_sha256", "uv_lock_sha256", "toolchain_sha256"):
        _hex(record[key], 64, f"producer {key}")
    validate_artifact_descriptor(record["source_distribution"])
    return record


def validate_raw_producer_reference(value: object) -> Mapping[str, object]:
    """Frozen v0.1.4 Section 5.1 RawProducerReference (no distribution slot)."""
    record = _ordered(value, RAW_REFERENCE_KEYS, "RawProducerReference")
    _hex(record["git_commit"], 40, "raw producer commit")
    for key in ("source_tree_sha256", "uv_lock_sha256", "toolchain_sha256"):
        _hex(record[key], 64, f"raw producer {key}")
    entry_id = record["raw_checkpoint_registry_entry_id"]
    if not isinstance(entry_id, str) or not 1 <= len(entry_id.encode()) <= 128:
        raise ValueError("raw checkpoint registry entry id must be 1..128 bytes")
    validate_relative_path(str(record["raw_checkpoint_manifest_path"]))
    _hex(
        record["raw_checkpoint_manifest_byte_sha256"],
        64,
        "raw checkpoint manifest hash",
    )
    return record


def _validate_incorporated_preregistration(record: Mapping[str, object]) -> None:
    """Frozen v0.1.5 Section 2.2: the packaged v0.1.4 and v0.1.3 copies are
    hash-bound as an ordered two-entry list."""
    entries = record["incorporated_pre_registrations"]
    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError("incorporated pre-registrations must list exactly two entries")
    for entry, registered in zip(entries, INCORPORATED_PREREGISTRATION_SHA256S, strict=True):
        if not isinstance(entry, dict) or tuple(entry.keys()) != (
            "path",
            "byte_sha256",
        ):
            raise ValueError("incorporated entry has missing or extra keys")
        validate_relative_path(str(entry["path"]))
        if _hex(entry["byte_sha256"], 64, "incorporated hash") != registered:
            raise ValueError("incorporated pre-registration digest mismatch")


def validate_limits(value: object) -> None:
    record = _ordered(value, tuple(key for key, _ in LIMITS_ITEMS), "LimitsRecord")
    for key, expected in LIMITS_ITEMS:
        if record[key] != expected or type(record[key]) is not type(expected):
            raise ValueError(f"registered limit changed: {key}")


def validate_checkpoint_manifest(value: object) -> Mapping[str, object]:
    record = _ordered(value, CHECKPOINT_KEYS, "checkpoint manifest")
    if record["schema_version"] != "pharos.quiet-negative-checkpoint-manifest.v0.1.4":
        raise ValueError("checkpoint schema mismatch")
    if record["status"] != "candidate" or record["state"] != "gaia_candidate_complete":
        raise ValueError("checkpoint status/state mismatch")
    _uuid4(record["attempt_id"])
    validate_relative_path(str(record["pre_registration_path"]))
    if (
        _hex(record["pre_registration_byte_sha256"], 64, "pre-registration hash")
        != PREREGISTRATION_SHA256
    ):
        raise ValueError("pre-registration digest mismatch")
    if record["pre_registration_bytes"] != PREREGISTRATION_BYTES:
        raise ValueError("pre-registration size mismatch")
    _validate_incorporated_preregistration(record)
    _timestamp(record["created_at_utc"])
    validate_producer(record["raw_producer"])
    if (
        record["gaia_logical_requests"] != 120
        or type(record["transport_attempt_count"]) is not int
        or record["transport_attempt_count"] < 120
    ):
        raise ValueError("checkpoint request counts invalid")
    _hex(record["request_order_rows_semantic_sha256"], 64, "request-order semantic hash")
    _hex(record["canonical_parent_rows_semantic_sha256"], 64, "parent semantic hash")
    validate_limits(record["limits"])
    return record


def validate_final_manifest(value: object) -> Mapping[str, object]:
    record = _ordered(value, FINAL_KEYS, "final manifest")
    if record["schema_version"] != "pharos.quiet-negative-manifest.v0.1.4":
        raise ValueError("final manifest schema mismatch")
    if record["status"] != "candidate" or record["state"] != "final_candidate_complete":
        raise ValueError("final candidate status/state mismatch")
    _uuid4(record["attempt_id"])
    if (
        record["pre_registration_byte_sha256"] != PREREGISTRATION_SHA256
        or record["pre_registration_bytes"] != PREREGISTRATION_BYTES
    ):
        raise ValueError("final pre-registration binding mismatch")
    _validate_incorporated_preregistration(record)
    for key in (
        "raw_checkpoint_manifest_byte_sha256",
        "request_order_rows_semantic_sha256",
        "canonical_parent_rows_semantic_sha256",
        "bp_rp_rows_semantic_sha256",
        "exclusions_semantic_sha256",
        "final_rows_semantic_sha256",
    ):
        _hex(record[key], 64, key)
    for key in ("raw_checkpoint_candidate_commit", "raw_checkpoint_review_evidence_commit"):
        _hex(record[key], 40, key)
    validate_raw_producer_reference(record["raw_producer"])
    validate_producer(record["release_producer"])
    if record["gaia_logical_requests"] != 120 or record["chen_logical_requests"] != 1:
        raise ValueError("final logical request counts invalid")
    bp_rp_rows = _strict_int(record["bp_rp_rows"], "bp_rp_rows")
    simbad_logical = _strict_int(record["simbad_logical_requests"], "simbad logical requests")
    if simbad_logical != (bp_rp_rows + 499) // 500:
        raise ValueError("SIMBAD logical request count mismatch")
    if record["total_logical_requests"] != 121 + simbad_logical:
        raise ValueError("total logical request count mismatch")
    if record["raw_rows"] != 55000 or not 50000 <= bp_rp_rows <= 55000:
        raise ValueError("raw/BP-RP row count invalid")
    simbad_normalized = _strict_int(record["simbad_normalized_rows"], "SIMBAD normalized rows")
    chen_normalized = _strict_int(record["chen_normalized_rows"], "Chen normalized rows")
    if record["exclusion_rows"] != simbad_normalized + chen_normalized:
        raise ValueError("exclusion row count mismatch")
    excluded_unique = _strict_int(record["excluded_unique_sources"], "excluded unique sources")
    final_rows = _strict_int(record["final_rows"], "final rows")
    if final_rows != bp_rp_rows - excluded_unique:
        raise ValueError("final set-difference count mismatch")
    if not 50000 <= final_rows <= 250000:
        raise ValueError("final row count outside registered bounds")
    exact_ids = {
        "bp_rp_algorithm_id": "bp-rp-derive-v014",
        "simbad_normalization_id": "simbad-local-exclusion-v014",
        "chen_match_id": "chen-local-exclusion-v014",
        "final_difference_id": "final-difference-v014",
    }
    if any(record[key] != expected for key, expected in exact_ids.items()):
        raise ValueError("final normalization ID mismatch")
    validate_limits(record["limits"])
    return record


_LOCAL_TRANSITIONS: Final = {
    None: {"initialized"},
    "initialized": {"gaia_acquiring", "failed"},
    "gaia_acquiring": {"gaia_candidate_complete", "failed"},
    "gaia_candidate_complete": {"bp_rp_derived", "failed"},
    "bp_rp_derived": {"external_acquiring", "failed"},
    "external_acquiring": {"final_candidate_complete", "failed"},
    "final_candidate_complete": set(),
    "failed": set(),
}
STATE_KEYS: Final = (
    "attempt_id",
    "event_sequence",
    "from_state",
    "to_state",
    "recorded_at_utc",
    "actor_role",
    "evidence_semantic_sha256",
    "previous_event_sha256",
)


def state_event_hash(event: Mapping[str, object]) -> str:
    if type(event) is not dict or set(event) != set(STATE_KEYS):
        raise ValueError("attempt state event has missing or extra keys")
    return hashlib.sha256(canonical_json(dict(event))).hexdigest()


def validate_state_events(events: Sequence[object]) -> str:
    if not events:
        raise ValueError("attempt state log is empty")
    previous_state: str | None = None
    previous_hash: str | None = None
    attempt_id: str | None = None
    for sequence, value in enumerate(events):
        if type(value) is not dict or set(value) != set(STATE_KEYS):
            raise ValueError("attempt state event has missing or extra keys")
        event = value
        current_attempt = _uuid4(event["attempt_id"])
        attempt_id = attempt_id or current_attempt
        if current_attempt != attempt_id or event["event_sequence"] != sequence:
            raise ValueError("attempt state sequence/identity mismatch")
        if (
            event["from_state"] != previous_state
            or event["to_state"] not in _LOCAL_TRANSITIONS[previous_state]
        ):
            raise ValueError("invalid attempt state transition")
        _timestamp(event["recorded_at_utc"])
        _hex(event["evidence_semantic_sha256"], 64, "state evidence")
        if event["previous_event_sha256"] != previous_hash:
            raise ValueError("attempt state hash chain mismatch")
        previous_state = str(event["to_state"])
        previous_hash = state_event_hash(event)
    if previous_state is None:
        raise AssertionError("non-empty state log ended without a state")
    return previous_state


def append_state_event(
    path: Path,
    *,
    attempt_id: str,
    to_state: str,
    actor_role: str,
    evidence_semantic_sha256: str,
) -> str:
    """Append one fsync'd exact transition to a private regular JSONL file."""
    _uuid4(attempt_id)
    _hex(evidence_semantic_sha256, 64, "state evidence")
    existing: list[dict[str, object]] = []
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("attempt state path is not a private regular file")
        for line in path.read_bytes().splitlines():
            item = json.loads(line)
            if type(item) is not dict:
                raise ValueError("attempt state line is not an object")
            existing.append(item)
        previous_state = validate_state_events(existing)
    else:
        previous_state = None
    previous_hash = state_event_hash(existing[-1]) if existing else None
    event: dict[str, object] = {
        "attempt_id": attempt_id,
        "event_sequence": len(existing),
        "from_state": previous_state,
        "to_state": to_state,
        "recorded_at_utc": timestamp_now(),
        "actor_role": actor_role,
        "evidence_semantic_sha256": evidence_semantic_sha256,
        "previous_event_sha256": previous_hash,
    }
    validate_state_events([*existing, event])
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "ab", closefd=False) as output:
            output.write(canonical_json(event) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(fd)
    return state_event_hash(event)


def validate_pass_report(value: object) -> Mapping[str, object]:
    record = _ordered(value, PASS_REPORT_KEYS, "pass report")
    if record["schema_version"] != "pharos.quiet-negative-pass-report.v0.1.4":
        raise ValueError("pass report schema mismatch")
    _uuid4(record["attempt_id"])
    if record["pre_registration_sha256"] != PREREGISTRATION_SHA256:
        raise ValueError("pass report pre-registration mismatch")
    _hex(record["raw_checkpoint_manifest_sha256"], 64, "checkpoint manifest hash")
    _timestamp(record["generated_at_utc"])
    validate_producer(record["producer"])
    gates = record["gates"]
    if type(gates) is not list or [item.get("gate_id") for item in gates if type(item) is dict] != [
        f"{i:02d}" for i in range(1, 13)
    ]:
        raise ValueError("pass report gates must be exactly 01..12")
    tests = record["test_results"]
    expected_tests = [
        "pytest",
        "ruff",
        "mypy",
        "build",
        "dependency_audit",
        "fuzz_smoke",
        "artifact_verify",
    ]
    if (
        type(tests) is not list
        or [item.get("test_id") for item in tests if type(item) is dict] != expected_tests
    ):
        raise ValueError("pass report test order is invalid")
    all_passed = all(type(item) is dict and item.get("passed") is True for item in gates) and all(
        type(item) is dict and item.get("exit_code") == 0 for item in tests
    )
    if record["all_passed"] is not all_passed:
        raise ValueError("pass report all_passed is inconsistent")
    attestation = record["no_model_fit_attestation"]
    if type(attestation) is not dict or attestation.get("passed") is not True:
        raise ValueError("no-model-fit attestation missing")
    return record


def validate_review_attestation(
    value: object, authorized_keys: tuple[str, ...]
) -> Mapping[str, object]:
    record = _ordered(value, REVIEW_KEYS, "review attestation")
    if record["schema_version"] != "pharos.control-review-attestation.v0.1.4":
        raise ValueError("review schema mismatch")
    if (
        record["review_role"] not in ("raw_checkpoint", "final_release")
        or record["outcome"] != "approved"
    ):
        raise ValueError("review role/outcome mismatch")
    _uuid4(record["attempt_id"])
    _hex(record["candidate_commit"], 40, "candidate commit")
    validate_relative_path(str(record["candidate_manifest_path"]))
    _hex(record["candidate_manifest_byte_sha256"], 64, "candidate manifest hash")
    if record["pre_registration_byte_sha256"] != PREREGISTRATION_SHA256:
        raise ValueError("review pre-registration mismatch")
    signing_key = _hex(record["reviewer_signing_key_sha256"], 64, "review signing key")
    if not authorized_keys or signing_key not in authorized_keys:
        raise PermissionError("review signing key trust root is empty or unauthorized")
    _timestamp(record["reviewed_at_utc"])
    expected_checks = [
        "tree",
        "manifest",
        "schemas",
        "counts",
        "queries",
        "transport",
        "resources",
        "reconstruction",
    ]
    if record["review_role"] == "final_release":
        expected_checks += ["tests", "no_model_fit"]
    checks = record["checks"]
    if (
        type(checks) is not list
        or [item.get("check_id") for item in checks if type(item) is dict] != expected_checks
        or not all(item.get("passed") is True for item in checks)
    ):
        raise ValueError("review checks are not role-complete and passing")
    return record

"""Immutable checkpoint packaging for the frozen v0.1.4 workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pandas as pd

from pharos.control_artifacts_v014 import (
    ArtifactIdentity,
    CandidateTreeWriter,
    semantic_sha256,
    sha256_bytes,
)
from pharos.control_evidence_v014 import (
    REQUEST_INDEX_COLUMNS,
    REQUEST_INDEX_SCHEMA,
    TRANSPORT_COLUMNS,
    TRANSPORT_SCHEMA,
    validate_request_index,
    validate_transport_attempts,
)
from pharos.control_manifests_v014 import (
    LIMITS_ITEMS,
    strict_yaml_dump,
    validate_checkpoint_manifest,
    validate_state_events,
)
from pharos.control_population_v014 import (
    CELLS,
    GAIA_DECODED_SCHEMA,
    GAIA_NORMALIZED_SCHEMA,
    GAIA_QUERY_TEMPLATE,
    INCORPORATED_PREREGISTRATION_SHA256,
    PREREGISTRATION_BYTES,
    PREREGISTRATION_SHA256,
    RAW_SCHEMA,
)
from pharos.control_provenance_v014 import (
    CA_BUNDLE_SHA256,
    ProducerIdentity,
    normalizer_registry,
    producer_identity,
    repository_root,
    source_distribution,
    toolchain_record,
    validate_ca_bundle,
)
from pharos.control_schemas_v014 import (
    GAIA_TABLE_COLUMNS,
    REQUEST_INDEX_TABLE_COLUMNS,
    TRANSPORT_TABLE_COLUMNS,
)
from pharos.control_workflow_v014 import GaiaAcquisitionSession

GAIA_ENDPOINT: Final = "https://gea.esac.esa.int/tap-server/tap"


def _descriptor(identity: ArtifactIdentity, role: str) -> dict[str, object]:
    return {
        "path": identity.path,
        "byte_sha256": identity.byte_sha256,
        "semantic_sha256": identity.semantic_sha256,
        "bytes": identity.bytes,
        "rows": identity.rows,
        "schema_version": identity.schema_version,
        "columns": list(identity.columns) if identity.columns is not None else None,
        "producer_role": role,
    }


def _write_text(
    writer: CandidateTreeWriter,
    relative: str,
    data: bytes,
    *,
    schema_version: str,
) -> ArtifactIdentity:
    identity = writer.write_bytes(relative, data)
    return ArtifactIdentity(
        identity.path,
        identity.byte_sha256,
        None,
        identity.bytes,
        None,
        schema_version,
        None,
    )


def _software_payloads(
    writer: CandidateTreeWriter,
    identity: ProducerIdentity,
    *,
    ca_bundle_path: Path,
) -> tuple[dict[str, ArtifactIdentity], dict[str, object]]:
    archive = source_distribution(identity)
    archive_hash = sha256_bytes(archive)
    source = _write_text(
        writer,
        f"software/pharos-seti-data-v0.1.4-source.{archive_hash}.tar",
        archive,
        schema_version="pharos.source-distribution.v1",
    )
    lock = (repository_root() / "uv.lock").read_bytes()
    lock_hash = sha256_bytes(lock)
    lock_artifact = _write_text(
        writer,
        f"software/uv.lock.{lock_hash}.txt",
        lock,
        schema_version="pharos.uv-lock.v1",
    )
    toolchain = toolchain_record(ca_bundle_path=ca_bundle_path)
    toolchain_bytes = strict_yaml_dump(toolchain)
    toolchain_hash = sha256_bytes(toolchain_bytes)
    toolchain_artifact = _write_text(
        writer,
        f"software/toolchain.{toolchain_hash}.yaml",
        toolchain_bytes,
        schema_version="pharos.toolchain.v1",
    )
    registry_payload: dict[str, object] = {
        "schema_version": "pharos.normalizer-registry.v1",
        "pre_registration_sha256": PREREGISTRATION_SHA256,
        "semantic_hash_algorithm": "pharos-semantic-frame-le-v1",
        "entries": normalizer_registry(identity),
    }
    registry_bytes = strict_yaml_dump(registry_payload)
    registry_hash = sha256_bytes(registry_bytes)
    normalizers = _write_text(
        writer,
        f"software/normalizer_registry.{registry_hash}.yaml",
        registry_bytes,
        schema_version="pharos.normalizer-registry.v1",
    )
    ca = validate_ca_bundle(ca_bundle_path)
    ca_artifact = _write_text(
        writer,
        f"software/ca_bundle.{CA_BUNDLE_SHA256}.pem",
        ca,
        schema_version="pharos.ca-bundle.v1",
    )
    return (
        {
            "source_distribution": source,
            "uv_lock": lock_artifact,
            "toolchain": toolchain_artifact,
            "normalizer_registry": normalizers,
            "ca_bundle": ca_artifact,
        },
        toolchain,
    )


def _request_index(
    session: GaiaAcquisitionSession,
    request_evidence: Sequence[tuple[ArtifactIdentity, ArtifactIdentity, ArtifactIdentity]],
    transport: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for plan, evidence in zip((item[0] for item in session.pages), request_evidence, strict=True):
        query, raw, normalized = evidence
        attempts = transport.loc[transport["logical_request_id"] == plan.logical_request_id]
        if attempts.empty:
            raise ValueError("Gaia logical request has no transport evidence")
        successful_fetch = attempts.loc[
            (attempts["outcome"] == "success") & (attempts["phase"] == "fetch")
        ]
        if len(successful_fetch) != 1:
            raise ValueError("Gaia logical request requires exactly one successful fetch")
        rows.append(
            {
                "attempt_id": session.attempt_id,
                "logical_request_id": plan.logical_request_id,
                "global_sequence": plan.global_sequence,
                "service": "gaia",
                "service_sequence": plan.service_sequence,
                "parent_kind": "selection_cell",
                "parent_start": plan.sweep * 500,
                "parent_rows": plan.requested_rows,
                "stratum_id": plan.cell.id,
                "cursor_before": plan.cursor_before,
                "requested_rows": plan.requested_rows,
                "query_path": query.path,
                "query_byte_sha256": query.byte_sha256,
                "input_path": None,
                "input_byte_sha256": None,
                "input_semantic_sha256": None,
                "raw_response_path": raw.path,
                "raw_response_byte_sha256": raw.byte_sha256,
                "raw_response_semantic_sha256": raw.semantic_sha256,
                "raw_response_rows": raw.rows,
                "normalized_response_path": normalized.path,
                "normalized_response_byte_sha256": normalized.byte_sha256,
                "normalized_response_semantic_sha256": normalized.semantic_sha256,
                "normalized_response_rows": normalized.rows,
                "simbad_radius_rejected_rows": None,
                "simbad_duplicate_rows_removed": None,
                "normalization_id": "gaia-page-normalize-v014",
                "successful_transport_ordinal": int(successful_fetch.iloc[0]["transport_ordinal"]),
                "first_started_at": attempts["started_at"].min(),
                "completed_at": attempts["finished_at"].max(),
            }
        )
    return pd.DataFrame(rows, columns=REQUEST_INDEX_COLUMNS)


def _state_bytes_validated(raw: bytes, attempt_id: str) -> None:
    events: list[object] = []
    for line in raw.splitlines():
        value = json.loads(line)
        events.append(value)
    if validate_state_events(events) != "gaia_candidate_complete":
        raise ValueError("checkpoint attempt state does not end gaia_candidate_complete")
    if any(
        not isinstance(event, Mapping) or event.get("attempt_id") != attempt_id for event in events
    ):
        raise ValueError("checkpoint attempt state identity mismatch")


def publish_gaia_checkpoint(
    *,
    session: GaiaAcquisitionSession,
    transport_attempts: pd.DataFrame,
    attempt_state_bytes: bytes,
    output_parent: Path,
    ca_bundle_path: Path,
) -> Path:
    """Package and no-replace publish the exact Gaia-only candidate tree."""
    parent = session.parent()
    if tuple(transport_attempts.columns) != TRANSPORT_COLUMNS:
        raise ValueError("transport table has missing, extra, duplicate, or reordered columns")
    _state_bytes_validated(attempt_state_bytes, session.attempt_id)
    identity = producer_identity()
    writer = CandidateTreeWriter(
        output_parent,
        session.attempt_id,
        manifest_name="checkpoint_manifest.yaml",
    )
    try:
        prereg = (repository_root() / "pre_registration/v0.1.4_control_population.md").read_bytes()
        packaged_prereg = _write_text(
            writer,
            f"pre_registration.v0.1.4.{PREREGISTRATION_SHA256}.md",
            prereg,
            schema_version="pharos.pre-registration.v0.1.4",
        )
        # Frozen v0.1.4 Section 5.5: package the incorporated v0.1.3 document
        # byte-identically so the effective protocol is self-contained.
        incorporated = (
            repository_root() / "pre_registration/v0.1.3_control_population.md"
        ).read_bytes()
        incorporated_prereg = _write_text(
            writer,
            "pre_registration.v0.1.3.b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43.md",
            incorporated,
            schema_version="pharos.pre-registration.v0.1.3",
        )
        software, _ = _software_payloads(writer, identity, ca_bundle_path=ca_bundle_path)
        return _finish_gaia_checkpoint(
            writer=writer,
            identity=identity,
            session=session,
            parent=parent,
            transport_attempts=transport_attempts,
            attempt_state_bytes=attempt_state_bytes,
            packaged_prereg=packaged_prereg,
            incorporated_prereg=incorporated_prereg,
            software=software,
        )
    except BaseException:
        # Failure leaves the private staging tree intact for explicit operator
        # quarantine/removal; only process-owned descriptors are released.
        writer.close_unpublished()
        raise


def _finish_gaia_checkpoint(
    *,
    writer: CandidateTreeWriter,
    identity: ProducerIdentity,
    session: GaiaAcquisitionSession,
    parent: pd.DataFrame,
    transport_attempts: pd.DataFrame,
    attempt_state_bytes: bytes,
    packaged_prereg: ArtifactIdentity,
    incorporated_prereg: ArtifactIdentity,
    software: dict[str, ArtifactIdentity],
) -> Path:
    request_evidence: list[tuple[ArtifactIdentity, ArtifactIdentity, ArtifactIdentity]] = []
    evidence_descriptors: list[dict[str, object]] = []
    for plan, decoded_raw, normalized in session.pages:
        query_hash = sha256_bytes(plan.query_text.encode())
        query = _write_text(
            writer,
            f"requests/gaia/{plan.service_sequence:04d}.query.{query_hash}.txt",
            plan.query_text.encode(),
            schema_version="pharos.query-text.v0.1.4",
        )
        raw = writer.write_content_addressed_parquet(
            "requests/gaia",
            f"{plan.service_sequence:04d}.raw_response",
            decoded_raw,
            schema_version=GAIA_DECODED_SCHEMA,
            columns=GAIA_TABLE_COLUMNS,
            source_tree_sha256=identity.source_tree_sha256,
            uv_lock_sha256=identity.uv_lock_sha256,
        )
        normalized_artifact = writer.write_content_addressed_parquet(
            "requests/gaia",
            f"{plan.service_sequence:04d}.normalized_response",
            normalized,
            schema_version=GAIA_NORMALIZED_SCHEMA,
            columns=GAIA_TABLE_COLUMNS,
            source_tree_sha256=identity.source_tree_sha256,
            uv_lock_sha256=identity.uv_lock_sha256,
        )
        request_evidence.append((query, raw, normalized_artifact))
        evidence_descriptors.extend(
            (
                _descriptor(query, "raw"),
                _descriptor(raw, "raw"),
                _descriptor(normalized_artifact, "raw"),
            )
        )
    request_index = _request_index(session, request_evidence, transport_attempts)
    validate_request_index(
        request_index, attempt_id=session.attempt_id, bp_rp_rows=None, final=False
    )
    validate_transport_attempts(
        transport_attempts, attempt_id=session.attempt_id, request_index=request_index
    )
    request_index_artifact = writer.write_content_addressed_parquet(
        "requests",
        "request_index",
        request_index,
        schema_version=REQUEST_INDEX_SCHEMA,
        columns=REQUEST_INDEX_TABLE_COLUMNS,
        source_tree_sha256=identity.source_tree_sha256,
        uv_lock_sha256=identity.uv_lock_sha256,
    )
    transport_artifact = writer.write_content_addressed_parquet(
        "requests",
        "transport_attempts",
        transport_attempts,
        schema_version=TRANSPORT_SCHEMA,
        columns=TRANSPORT_TABLE_COLUMNS,
        source_tree_sha256=identity.source_tree_sha256,
        uv_lock_sha256=identity.uv_lock_sha256,
    )
    raw_artifact = writer.write_content_addressed_parquet(
        ".",
        "raw_candidates",
        parent,
        schema_version=RAW_SCHEMA,
        columns=GAIA_TABLE_COLUMNS,
        source_tree_sha256=identity.source_tree_sha256,
        uv_lock_sha256=identity.uv_lock_sha256,
    )
    state = _write_text(
        writer,
        "attempt_state.jsonl",
        attempt_state_bytes,
        schema_version="pharos.attempt-state.v0.1.4",
    )
    source_descriptor = _descriptor(software["source_distribution"], "raw")
    producer = {
        "git_commit": identity.git_commit,
        "source_tree_sha256": identity.source_tree_sha256,
        "uv_lock_sha256": identity.uv_lock_sha256,
        "toolchain_sha256": software["toolchain"].byte_sha256,
        "source_distribution": source_descriptor,
    }
    template_hash = hashlib.sha256(GAIA_QUERY_TEMPLATE.encode()).hexdigest()
    retrieved = request_index["completed_at"].max().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    catalog_releases = [
        {
            "service": service,
            "endpoint": GAIA_ENDPOINT,
            "catalog_id": catalog,
            "release_id": release,
            "retrieved_at_utc": retrieved,
            "query_template_byte_sha256": template_hash,
        }
        for service, catalog, release in (
            ("gaia", "gaiadr3.gaia_source", "Gaia DR3"),
            ("allwise", "gaiadr1.allwise_original_valid", "AllWISE Source Catalog"),
            ("tmass", "gaiadr1.tmass_original_valid", "2MASS All-Sky Point Source Catalog"),
        )
    ]
    selection = {
        "strategy": "24-cell-round-robin-keyset-v1",
        "target_rows": 55000,
        "cell_order": [cell.id for cell in CELLS],
        "cells": [
            {
                "id": state_item.cell.id,
                "ordinal": state_item.cell.ordinal,
                "longitude_min": state_item.cell.longitude_min,
                "longitude_max": state_item.cell.longitude_max,
                "hemisphere": state_item.cell.hemisphere,
                "quota": state_item.cell.quota,
                "cursor": state_item.cursor,
                "collected_rows": state_item.collected_rows,
            }
            for state_item in session.planner.progress
        ],
    }
    request_order = pd.concat([normalized for _, _, normalized in session.pages], ignore_index=True)
    manifest: dict[str, object] = {
        "schema_version": "pharos.quiet-negative-checkpoint-manifest.v0.1.4",
        "status": "candidate",
        "attempt_id": session.attempt_id,
        "state": "gaia_candidate_complete",
        "pre_registration_path": packaged_prereg.path,
        "pre_registration_byte_sha256": PREREGISTRATION_SHA256,
        "pre_registration_bytes": PREREGISTRATION_BYTES,
        "incorporated_pre_registration_path": incorporated_prereg.path,
        "incorporated_pre_registration_byte_sha256": INCORPORATED_PREREGISTRATION_SHA256,
        "created_at_utc": retrieved,
        "raw_producer": producer,
        "catalog_releases": catalog_releases,
        "selection": selection,
        "gaia_logical_requests": 120,
        "transport_attempt_count": len(transport_attempts),
        "artifacts": {
            "packaged_pre_registration": _descriptor(packaged_prereg, "raw"),
            "incorporated_pre_registration": _descriptor(incorporated_prereg, "raw"),
            "source_distribution": source_descriptor,
            "uv_lock": _descriptor(software["uv_lock"], "raw"),
            "toolchain": _descriptor(software["toolchain"], "raw"),
            "normalizer_registry": _descriptor(software["normalizer_registry"], "raw"),
            "ca_bundle": _descriptor(software["ca_bundle"], "raw"),
            "request_index": _descriptor(request_index_artifact, "raw"),
            "transport_attempts": _descriptor(transport_artifact, "raw"),
            "request_evidence": evidence_descriptors,
            "raw_candidates": _descriptor(raw_artifact, "raw"),
            "attempt_state": _descriptor(state, "raw"),
        },
        "request_order_rows_semantic_sha256": semantic_sha256(
            request_order, RAW_SCHEMA, GAIA_TABLE_COLUMNS
        ),
        "canonical_parent_rows_semantic_sha256": raw_artifact.semantic_sha256,
        "limits": dict(LIMITS_ITEMS),
    }
    validate_checkpoint_manifest(manifest)
    return writer.publish(strict_yaml_dump(manifest))

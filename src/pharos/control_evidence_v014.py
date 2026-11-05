"""Exact logical-request and transport evidence schemas for v0.1.4."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any, Final

import pandas as pd
from pandas.api.types import is_integer_dtype

from pharos.control_artifacts_v014 import validate_relative_path
from pharos.control_population_v014 import (
    GAIA_LOGICAL_REQUESTS,
    SIMBAD_MAXREC,
    SOURCE_BATCH_ROWS,
)

REQUEST_INDEX_SCHEMA: Final = "pharos.remote-request-index.v0.1.4"
TRANSPORT_SCHEMA: Final = "pharos.remote-transport-attempts.v0.1.4"
REQUEST_INDEX_COLUMNS: Final = (
    "attempt_id",
    "logical_request_id",
    "global_sequence",
    "service",
    "service_sequence",
    "parent_kind",
    "parent_start",
    "parent_rows",
    "stratum_id",
    "cursor_before",
    "requested_rows",
    "query_path",
    "query_byte_sha256",
    "input_path",
    "input_byte_sha256",
    "input_semantic_sha256",
    "raw_response_path",
    "raw_response_byte_sha256",
    "raw_response_semantic_sha256",
    "raw_response_rows",
    "normalized_response_path",
    "normalized_response_byte_sha256",
    "normalized_response_semantic_sha256",
    "normalized_response_rows",
    "simbad_radius_rejected_rows",
    "simbad_duplicate_rows_removed",
    "normalization_id",
    "successful_transport_ordinal",
    "first_started_at",
    "completed_at",
)
TRANSPORT_COLUMNS: Final = (
    "attempt_id",
    "logical_request_id",
    "transport_ordinal",
    "phase",
    "started_at",
    "finished_at",
    "outcome",
    "http_status",
    "expected_hostname",
    "peer_ip",
    "peer_port",
    "leaf_certificate_sha256",
    "tls_version",
    "redirect_count",
    "wire_bytes",
    "decompressed_bytes",
    "wire_sha256",
    "decompressed_sha256",
    "error_code",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^(gaia|simbad|chen)-\d{4}$")
_HOSTS = {
    "gaia": "gea.esac.esa.int",
    "simbad": "simbad.cds.unistra.fr",
    "chen": "vizier.cds.unistra.fr",
}


def _exact(frame: pd.DataFrame, expected: Sequence[str], context: str) -> None:
    if tuple(frame.columns) != tuple(expected) or len(frame.columns) != len(set(frame.columns)):
        raise ValueError(f"{context} has missing, extra, duplicate, or reordered columns")


def _uuid4(value: object) -> str:
    if type(value) is not str:
        raise TypeError("attempt_id must be string")
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("attempt_id is not canonical UUIDv4")
    return value


def _hash(value: object, name: str, *, nullable: bool = False) -> None:
    if value is None or pd.isna(value):
        if nullable:
            return
        raise ValueError(f"{name} is null")
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} is not lowercase SHA-256")


def _nullable_group(row: object, names: Sequence[str], required: bool) -> None:
    values = [getattr(row, name) for name in names]
    present = [value is not None and not pd.isna(value) for value in values]
    if required and not all(present):
        raise ValueError(f"required fields absent: {names}")
    if not required and any(present) and not all(present):
        raise ValueError(f"nullable fields are only valid as a complete group: {names}")


def validate_request_index(
    frame: pd.DataFrame,
    *,
    attempt_id: str,
    bp_rp_rows: int | None,
    final: bool,
) -> None:
    _exact(frame, REQUEST_INDEX_COLUMNS, "request index")
    _uuid4(attempt_id)
    expected_count = GAIA_LOGICAL_REQUESTS
    simbad_count = 0
    if final:
        if type(bp_rp_rows) is not int or not 50_000 <= bp_rp_rows <= 55_000:
            raise ValueError("final request index requires registered BP/RP count")
        simbad_count = (bp_rp_rows + SOURCE_BATCH_ROWS - 1) // SOURCE_BATCH_ROWS
        expected_count += simbad_count + 1
    if len(frame) != expected_count:
        raise ValueError("logical request count mismatch")
    if not is_integer_dtype(frame["global_sequence"].dtype) or list(
        frame["global_sequence"].astype(int)
    ) != list(range(len(frame))):
        raise ValueError("global request sequence is not contiguous")
    if frame["logical_request_id"].duplicated().any() or frame["query_path"].duplicated().any():
        raise ValueError("logical request ID or query path duplicates")
    if not frame["attempt_id"].eq(attempt_id).all():
        raise ValueError("request index mixes attempt IDs")
    simbad_ranges: list[tuple[int, int]] = []
    expected_service_seq = {"gaia": 0, "simbad": 0, "chen": 0}
    for row in frame.itertuples(index=False):
        service = str(row.service)
        if (
            service not in expected_service_seq
            or _REQUEST_ID.fullmatch(str(row.logical_request_id)) is None
        ):
            raise ValueError("request service/logical ID invalid")
        if not str(row.logical_request_id).startswith(service + "-"):
            raise ValueError("logical request ID service mismatch")
        if int(row.service_sequence) != expected_service_seq[service]:
            raise ValueError("service request sequence is not contiguous")
        expected_service_seq[service] += 1
        if int(row.parent_start) < 0 or int(row.parent_rows) < 0:
            raise ValueError("request parent range invalid")
        if not 1 <= int(row.requested_rows) <= (10_000 if service == "chen" else 500):
            raise ValueError("request row ceiling invalid")
        if service == "chen" and int(row.requested_rows) != 10_000:
            raise ValueError("Chen requested_rows must be the 10,000-row ceiling")
        for path_name in ("query_path", "raw_response_path", "normalized_response_path"):
            validate_relative_path(str(getattr(row, path_name)))
        for digest_name in (
            "query_byte_sha256",
            "raw_response_byte_sha256",
            "raw_response_semantic_sha256",
            "normalized_response_byte_sha256",
            "normalized_response_semantic_sha256",
        ):
            _hash(getattr(row, digest_name), digest_name)
        has_input = service == "simbad"
        _nullable_group(
            row, ("input_path", "input_byte_sha256", "input_semantic_sha256"), has_input
        )
        if has_input:
            validate_relative_path(str(row.input_path))
            _hash(row.input_byte_sha256, "input byte hash")
            _hash(row.input_semantic_sha256, "input semantic hash")
        if service == "gaia":
            if not (
                int(row.requested_rows)
                == int(row.raw_response_rows)
                == int(row.normalized_response_rows)
            ):
                raise ValueError("Gaia request/response count mismatch")
            if (
                row.parent_kind != "selection_cell"
                or row.stratum_id is None
                or pd.isna(row.cursor_before)
            ):
                raise ValueError("Gaia parent/cell/cursor fields invalid")
        elif service == "simbad":
            if (
                row.parent_kind != "bp_rp_survivors"
                or row.stratum_id is not None
                or not pd.isna(row.cursor_before)
            ):
                raise ValueError("SIMBAD parent fields invalid")
            rejected = int(row.simbad_radius_rejected_rows)
            duplicates = int(row.simbad_duplicate_rows_removed)
            if (
                rejected < 0
                or duplicates < 0
                or int(row.raw_response_rows) - rejected - duplicates
                != int(row.normalized_response_rows)
            ):
                raise ValueError("SIMBAD normalization counts inconsistent")
            if int(row.raw_response_rows) >= SIMBAD_MAXREC:
                raise ValueError("SIMBAD response reached truncation sentinel")
            simbad_ranges.append((int(row.parent_start), int(row.parent_rows)))
        else:
            if (
                row.parent_kind != "catalog_descriptor"
                or int(row.parent_start) != 0
                or int(row.parent_rows) != 0
            ):
                raise ValueError("Chen parent descriptor fields invalid")
            if int(row.raw_response_rows) >= 10_000:
                raise ValueError("Chen response reached truncation sentinel")
        if service != "simbad" and (
            not pd.isna(row.simbad_radius_rejected_rows)
            or not pd.isna(row.simbad_duplicate_rows_removed)
        ):
            raise ValueError("SIMBAD-only counts appear on another service")
        if int(row.successful_transport_ordinal) < 1:
            raise ValueError("successful transport ordinal invalid")
        if row.completed_at < row.first_started_at:
            raise ValueError("logical request timestamps regress")
    if (
        expected_service_seq["gaia"] != 120
        or expected_service_seq["simbad"] != simbad_count
        or expected_service_seq["chen"] != int(final)
    ):
        raise ValueError("per-service request counts mismatch")
    if final:
        cursor = 0
        for start, count in simbad_ranges:
            if start != cursor or count < 1 or count > 500:
                raise ValueError("SIMBAD chunks overlap, omit, or reorder parent")
            cursor += count
        if cursor != bp_rp_rows:
            raise ValueError("SIMBAD chunks do not exactly partition BP/RP parent")


def validate_transport_attempts(
    frame: pd.DataFrame, *, attempt_id: str, request_index: pd.DataFrame
) -> None:
    _exact(frame, TRANSPORT_COLUMNS, "transport attempts")
    _uuid4(attempt_id)
    logical_ids = list(request_index["logical_request_id"])
    grouped: dict[str, list[Any]] = {value: [] for value in logical_ids}
    from pharos.control_network_v014 import validate_transport_attempt

    for raw_row in frame.to_dict("records"):
        # Pandas timestamps and nullable scalars are converted into the strict
        # ordinary-Python row consumed by the authoritative boundary.
        row = dict(raw_row)
        import datetime as _dt

        for key in ("started_at", "finished_at"):
            value = row[key]
            if isinstance(value, pd.Timestamp):
                value = value.to_pydatetime()
            if isinstance(value, _dt.datetime) and value.tzinfo is not None:
                if value.tzinfo is not _dt.timezone.utc:
                    value = value.astimezone(_dt.timezone.utc)
                row[key] = value
            elif isinstance(value, str) and value.endswith("Z"):
                row[key] = _dt.datetime.fromisoformat(value[:-1]).replace(
                    tzinfo=_dt.timezone.utc
                )
        for key in ("http_status", "error_code"):
            if pd.isna(row[key]):
                row[key] = None
        # DataFrame rows carry numpy scalars; the strict boundary consumes
        # ordinary Python types only.
        for key, value in list(row.items()):
            if hasattr(value, "item") and not isinstance(value, (str, bytes)):
                try:
                    row[key] = value.item()
                except (AttributeError, ValueError):
                    pass
        status_value = row["http_status"]
        if isinstance(status_value, float):
            row["http_status"] = int(status_value)
        for key in ("transport_ordinal", "peer_port", "redirect_count", "wire_bytes", "decompressed_bytes"):
            value = row[key]
            if isinstance(value, float) and value.is_integer():
                row[key] = int(value)
        validated = validate_transport_attempt(row)
        if validated.attempt_id != attempt_id or validated.logical_request_id not in grouped:
            raise ValueError("transport attempt has wrong attempt/logical request ID")
        grouped[validated.logical_request_id].append(validated)
    for request_row in request_index.itertuples(index=False):
        attempts = grouped[str(request_row.logical_request_id)]
        if not attempts or [int(row.transport_ordinal) for row in attempts] != list(
            range(1, len(attempts) + 1)
        ):
            raise ValueError("transport ordinals are not contiguous from one")
        if len(attempts) > 723:  # Gaia may have three submit/fetch attempts plus 720 polls.
            raise ValueError("transport child count exceeds registered absolute ceiling")
        successful = [row for row in attempts if row.outcome == "success"]
        if int(request_row.successful_transport_ordinal) not in {
            int(row.transport_ordinal) for row in successful
        }:
            raise ValueError("request index points to a non-success transport child")
        expected_host = _HOSTS[str(request_row.service)]
        for row in attempts:
            if row.expected_hostname != expected_host:
                raise ValueError("transport TLS/host/redirect contract mismatch")

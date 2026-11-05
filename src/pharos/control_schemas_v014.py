"""Exact ordered Arrow/semantic table schemas registered for Pharos v0.1.4."""

from __future__ import annotations

from typing import Final

from pharos.control_artifacts_v014 import Column
from pharos.control_evidence_v014 import REQUEST_INDEX_COLUMNS, TRANSPORT_COLUMNS
from pharos.control_population_v014 import (
    BP_RP_COLUMNS,
    CHEN_RAW_COLUMNS,
    EXCLUSION_COLUMNS,
    GAIA_COLUMNS,
    SIMBAD_RAW_COLUMNS,
    SIMBAD_UPLOAD_COLUMNS,
)


def _columns(
    names: tuple[str, ...],
    *,
    integer: frozenset[str] = frozenset(),
    boolean: frozenset[str] = frozenset(),
    string: frozenset[str] = frozenset(),
    timestamp: frozenset[str] = frozenset(),
    nullable: frozenset[str] = frozenset(),
) -> tuple[Column, ...]:
    result: list[Column] = []
    for name in names:
        logical = "float64"
        if name in integer:
            logical = "int64"
        elif name in boolean:
            logical = "bool"
        elif name in string:
            logical = "string"
        elif name in timestamp:
            logical = "timestamp[us,UTC]"
        result.append(Column(name, logical, name in nullable))  # type: ignore[arg-type]
    return tuple(result)


_GAIA_INTEGER = frozenset(
    {
        "gaia_dr3_source_id",
        "non_single_star",
        "wise_xm_n_neighbours",
        "wise_xm_n_mates",
        "wise_xm_flag",
        "allwise_ext_flg",
    }
)
_GAIA_STRING = frozenset({"allwise_designation", "allwise_cc_flags", "tmass_designation"})
_GAIA_NULLABLE = frozenset(
    {
        "pmra",
        "pmdec",
        "astrometric_excess_noise",
        "astrometric_excess_noise_sig",
        "ipd_frac_multi_peak",
        "ipd_frac_odd_win",
        "logg_gspphot",
        "distance_gspphot",
        "ag_gspphot",
        "w4mpro",
        "w4mpro_error",
        "w4snr",
        "allwise_cc_flags",
        "allwise_ext_flg",
        "tmass_j_m",
        "tmass_j_msigcom",
        "tmass_h_m",
        "tmass_h_msigcom",
    }
)
GAIA_TABLE_COLUMNS: Final = _columns(
    GAIA_COLUMNS,
    integer=_GAIA_INTEGER,
    boolean=frozenset({"duplicated_source"}),
    string=_GAIA_STRING,
    nullable=_GAIA_NULLABLE,
)
BP_RP_TABLE_COLUMNS: Final = GAIA_TABLE_COLUMNS + tuple(
    Column(name, "float64", False) for name in BP_RP_COLUMNS[len(GAIA_COLUMNS) :]
)
SIMBAD_UPLOAD_TABLE_COLUMNS: Final = _columns(
    SIMBAD_UPLOAD_COLUMNS, integer=frozenset({"gaia_dr3_source_id"})
)
SIMBAD_RAW_TABLE_COLUMNS: Final = _columns(
    SIMBAD_RAW_COLUMNS,
    integer=frozenset({"gaia_dr3_source_id"}),
    string=frozenset({"matched_object_id", "matched_otype"}),
)
CHEN_RAW_TABLE_COLUMNS: Final = _columns(
    CHEN_RAW_COLUMNS,
    integer=frozenset({"_raw_row_index"}),
    string=frozenset({"Name"}),
)
EXCLUSION_TABLE_COLUMNS: Final = _columns(
    EXCLUSION_COLUMNS,
    integer=frozenset({"gaia_dr3_source_id"}),
    string=frozenset(
        {
            "exclusion_catalog",
            "exclusion_class",
            "matched_object_id",
            "matched_otype",
            "catalog_release",
        }
    ),
)

_REQUEST_INTEGER = frozenset(
    {
        "global_sequence",
        "service_sequence",
        "parent_start",
        "parent_rows",
        "cursor_before",
        "requested_rows",
        "raw_response_rows",
        "normalized_response_rows",
        "simbad_radius_rejected_rows",
        "simbad_duplicate_rows_removed",
        "successful_transport_ordinal",
    }
)
_REQUEST_TIMESTAMP = frozenset({"first_started_at", "completed_at"})
_REQUEST_NULLABLE = frozenset(
    {
        "stratum_id",
        "cursor_before",
        "input_path",
        "input_byte_sha256",
        "input_semantic_sha256",
        "simbad_radius_rejected_rows",
        "simbad_duplicate_rows_removed",
    }
)
REQUEST_INDEX_TABLE_COLUMNS: Final = _columns(
    REQUEST_INDEX_COLUMNS,
    integer=_REQUEST_INTEGER,
    string=frozenset(REQUEST_INDEX_COLUMNS) - _REQUEST_INTEGER - _REQUEST_TIMESTAMP,
    timestamp=_REQUEST_TIMESTAMP,
    nullable=_REQUEST_NULLABLE,
)
_TRANSPORT_INTEGER = frozenset(
    {
        "transport_ordinal",
        "http_status",
        "peer_port",
        "redirect_count",
        "wire_bytes",
        "decompressed_bytes",
    }
)
_TRANSPORT_TIMESTAMP = frozenset({"started_at", "finished_at"})
TRANSPORT_TABLE_COLUMNS: Final = _columns(
    TRANSPORT_COLUMNS,
    integer=_TRANSPORT_INTEGER,
    string=frozenset(TRANSPORT_COLUMNS) - _TRANSPORT_INTEGER - _TRANSPORT_TIMESTAMP,
    timestamp=_TRANSPORT_TIMESTAMP,
    nullable=frozenset({"http_status", "error_code"}),
)

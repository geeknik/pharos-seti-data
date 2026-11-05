"""Frozen scientific mechanics for the Pharos v0.1.4 control population.

This module is deliberately free of network and filesystem side effects.  It
contains the exact twenty-four-cell plan, query rendering, strict response
normalizers, binary64 spherical matcher, and release derivations registered in
``pre_registration/v0.1.4_control_population.md``.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from dataclasses import dataclass, replace
from typing import Final, Iterable, Sequence, cast

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_float_dtype, is_integer_dtype

PREREGISTRATION_SHA256: Final = "62f1b74efd85fb6f36203094c27a947bf2a16e77c0b5ee428a749e55142aeb49"
PREREGISTRATION_BYTES: Final = 4_454
# Frozen v0.1.4 Section 5.5: every v0.1.4 tree also packages the incorporated
# v0.1.3 pre-registration byte-identically under its frozen v0.1.3 digest.
INCORPORATED_PREREGISTRATION_SHA256S: Final = (
    "54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650",
    "7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d",
    "ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b",
    "b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43",
)
INCORPORATED_PREREGISTRATION_BYTES: Final = (5_679, 5_925, 17_714, 87_851)
TARGET_ROWS: Final = 55_000
SOURCE_BATCH_ROWS: Final = 500
CELL_COUNT: Final = 24
GAIA_LOGICAL_REQUESTS: Final = 120
SIMBAD_DISCOVERY_RADIUS_ARCSEC: Final = 30.1
EXCLUSION_RADIUS_ARCSEC: Final = 30.0
SIMBAD_MAXREC: Final = 50_001
MAX_MATCHES_PER_SOURCE_CATALOG: Final = 100
CHEN_ROW_LIMIT: Final = 10_000
CHEN_CATALOG: Final = "J/ApJS/211/25/catalog"
CHEN_RELEASE: Final = "VizieR J/ApJS/211/25/catalog; 2021-08-10 release"
SIMBAD_RELEASE: Final = "SIMBAD live database"
PI: Final = float.fromhex("0x1.921fb54442d18p+1")

GAIA_DECODED_SCHEMA: Final = "pharos.gaia-decoded-page.v0.1.4"
GAIA_NORMALIZED_SCHEMA: Final = "pharos.gaia-normalized-page.v0.1.4"
RAW_SCHEMA: Final = "pharos.quiet-negative-raw.v0.1.4"
BP_RP_SCHEMA: Final = "pharos.quiet-negative-bp-rp.v0.1.4"
SIMBAD_UPLOAD_SCHEMA: Final = "pharos.simbad-upload.v0.1.4"
SIMBAD_RAW_SCHEMA: Final = "pharos.simbad-decoded-raw.v0.1.4"
CHEN_RAW_SCHEMA: Final = "pharos.chen-decoded-raw.v0.1.4"
EXCLUSION_SCHEMA: Final = "pharos.quiet-negative-exclusions.v0.1.4"
FINAL_SCHEMA: Final = "pharos.quiet-negative.v0.1.4"

GAIA_COLUMNS: Final = (
    "gaia_dr3_source_id",
    "ra",
    "dec",
    "galactic_l",
    "galactic_b",
    "parallax",
    "parallax_error",
    "parallax_over_error",
    "pmra",
    "pmdec",
    "ruwe",
    "astrometric_excess_noise",
    "astrometric_excess_noise_sig",
    "phot_g_mean_mag",
    "phot_bp_rp_excess_factor",
    "ipd_frac_multi_peak",
    "ipd_frac_odd_win",
    "duplicated_source",
    "non_single_star",
    "qso_probability",
    "galaxy_probability",
    "teff_gspphot",
    "logg_gspphot",
    "distance_gspphot",
    "ag_gspphot",
    "wise_xm_angular_distance",
    "wise_xm_n_neighbours",
    "wise_xm_n_mates",
    "wise_xm_flag",
    "allwise_designation",
    "w1mpro",
    "w1mpro_error",
    "w1snr",
    "w2mpro",
    "w2mpro_error",
    "w2snr",
    "w3mpro",
    "w3mpro_error",
    "w3snr",
    "w4mpro",
    "w4mpro_error",
    "w4snr",
    "allwise_cc_flags",
    "allwise_ext_flg",
    "tmass_xm_angular_distance",
    "tmass_designation",
    "tmass_j_m",
    "tmass_j_msigcom",
    "tmass_h_m",
    "tmass_h_msigcom",
    "tmass_ks_m",
    "tmass_ks_msigcom",
)
BP_RP_COLUMNS: Final = GAIA_COLUMNS + (
    "gmag_bin_lower",
    "bp_rp_excess_bin_median",
    "bp_rp_excess_delta",
)
SIMBAD_UPLOAD_COLUMNS: Final = ("gaia_dr3_source_id", "ra", "dec")
SIMBAD_RAW_COLUMNS: Final = (
    "gaia_dr3_source_id",
    "matched_object_id",
    "matched_otype",
    "matched_ra",
    "matched_dec",
    "server_angular_distance_arcsec",
)
CHEN_RAW_COLUMNS: Final = ("_RA", "_DE", "Name", "_raw_row_index")
EXCLUSION_COLUMNS: Final = (
    "gaia_dr3_source_id",
    "exclusion_catalog",
    "exclusion_class",
    "matched_object_id",
    "matched_otype",
    "angular_distance_arcsec",
    "catalog_release",
)
SIMBAD_YSO_TYPES: Final = frozenset({"Y*O", "Or*", "TT*", "Ae*", "HH", "out"})
SIMBAD_AGN_TYPES: Final = frozenset({"AGN", "SyG", "Sy1", "Sy2", "rG", "LIN", "QSO", "Bla", "BLL"})
SIMBAD_TYPES: Final = SIMBAD_YSO_TYPES | SIMBAD_AGN_TYPES


@dataclass(frozen=True)
class Cell:
    """One registered Galactic-longitude/hemisphere acquisition cell."""

    id: str
    ordinal: int
    longitude_min: float
    longitude_max: float
    hemisphere: str
    quota: int


def _build_cells() -> tuple[Cell, ...]:
    cells: list[Cell] = []
    ordinal = 0
    for lower in range(0, 360, 30):
        for hemisphere in ("north", "south"):
            quota = TARGET_ROWS // CELL_COUNT + (ordinal < TARGET_ROWS % CELL_COUNT)
            cells.append(
                Cell(
                    id=f"l{lower:03d}-{lower + 30:03d}-{hemisphere}",
                    ordinal=ordinal,
                    longitude_min=float(lower),
                    longitude_max=float(lower + 30),
                    hemisphere=hemisphere,
                    quota=int(quota),
                )
            )
            ordinal += 1
    return tuple(cells)


CELLS: Final = _build_cells()
CELL_BY_ID: Final = {cell.id: cell for cell in CELLS}


@dataclass(frozen=True)
class CellProgress:
    cell: Cell
    cursor: int = 0
    collected_rows: int = 0

    @property
    def complete(self) -> bool:
        return self.collected_rows == self.cell.quota

    @property
    def next_requested_rows(self) -> int:
        return min(SOURCE_BATCH_ROWS, self.cell.quota - self.collected_rows)


@dataclass(frozen=True)
class GaiaRequestPlan:
    logical_request_id: str
    global_sequence: int
    service_sequence: int
    sweep: int
    cell: Cell
    cursor_before: int
    requested_rows: int
    query_text: str
    query_byte_sha256: str


@dataclass(frozen=True)
class GaiaPlanner:
    """Immutable round-robin planner whose state is safe to checkpoint."""

    progress: tuple[CellProgress, ...] = tuple(CellProgress(cell) for cell in CELLS)
    completed_requests: int = 0

    def next_request(self) -> GaiaRequestPlan | None:
        if self.completed_requests == GAIA_LOGICAL_REQUESTS:
            return None
        sweep, ordinal = divmod(self.completed_requests, CELL_COUNT)
        state = self.progress[ordinal]
        if state.complete:
            raise ValueError("planner encountered an early-complete cell")
        requested = state.next_requested_rows
        if sweep < 4 and requested != SOURCE_BATCH_ROWS:
            raise ValueError("planner quota drifted before the final sweep")
        query = render_gaia_query(state.cell, state.cursor, requested)
        return GaiaRequestPlan(
            logical_request_id=f"gaia-{self.completed_requests:04d}",
            global_sequence=self.completed_requests,
            service_sequence=self.completed_requests,
            sweep=sweep,
            cell=state.cell,
            cursor_before=state.cursor,
            requested_rows=requested,
            query_text=query,
            query_byte_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
        )

    def accept_page(self, plan: GaiaRequestPlan, page: pd.DataFrame) -> GaiaPlanner:
        expected = self.next_request()
        if expected != plan:
            raise ValueError("page does not belong to the next registered logical request")
        normalized = normalize_gaia_page(
            page,
            cell=plan.cell,
            cursor_before=plan.cursor_before,
            requested_rows=plan.requested_rows,
        )
        ids = normalized["gaia_dr3_source_id"].to_numpy(dtype=np.int64)
        updated = replace(
            self.progress[plan.cell.ordinal],
            cursor=int(ids[-1]),
            collected_rows=(self.progress[plan.cell.ordinal].collected_rows + len(normalized)),
        )
        progress = list(self.progress)
        progress[plan.cell.ordinal] = updated
        result = GaiaPlanner(tuple(progress), self.completed_requests + 1)
        if result.completed_requests == GAIA_LOGICAL_REQUESTS:
            if any(not item.complete for item in result.progress):
                raise ValueError("planner finished without satisfying every cell quota")
            if sum(item.collected_rows for item in result.progress) != TARGET_ROWS:
                raise ValueError("planner target row count is inconsistent")
        return result


GAIA_QUERY_TEMPLATE: Final = """SELECT TOP {REQUEST_ROWS}
  gs.source_id AS gaia_dr3_source_id,
  gs.ra,
  gs.dec,
  gs.l AS galactic_l,
  gs.b AS galactic_b,
  gs.parallax,
  gs.parallax_error,
  gs.parallax_over_error,
  gs.pmra,
  gs.pmdec,
  gs.ruwe,
  gs.astrometric_excess_noise,
  gs.astrometric_excess_noise_sig,
  gs.phot_g_mean_mag,
  gs.phot_bp_rp_excess_factor,
  gs.ipd_frac_multi_peak,
  gs.ipd_frac_odd_win,
  gs.duplicated_source,
  gs.non_single_star,
  gs.classprob_dsc_combmod_quasar AS qso_probability,
  gs.classprob_dsc_combmod_galaxy AS galaxy_probability,
  gs.teff_gspphot,
  gs.logg_gspphot,
  gs.distance_gspphot,
  gs.ag_gspphot,
  awbn.angular_distance AS wise_xm_angular_distance,
  awbn.number_of_neighbours AS wise_xm_n_neighbours,
  awbn.number_of_mates AS wise_xm_n_mates,
  awbn.xm_flag AS wise_xm_flag,
  aw.designation AS allwise_designation,
  aw.w1mpro,
  aw.w1mpro_error,
  (1.0857 / aw.w1mpro_error) AS w1snr,
  aw.w2mpro,
  aw.w2mpro_error,
  (1.0857 / aw.w2mpro_error) AS w2snr,
  aw.w3mpro,
  aw.w3mpro_error,
  (1.0857 / aw.w3mpro_error) AS w3snr,
  aw.w4mpro,
  aw.w4mpro_error,
  (1.0857 / aw.w4mpro_error) AS w4snr,
  aw.cc_flags AS allwise_cc_flags,
  aw.ext_flag AS allwise_ext_flg,
  tmbn.angular_distance AS tmass_xm_angular_distance,
  tm.designation AS tmass_designation,
  tm.j_m AS tmass_j_m,
  tm.j_msigcom AS tmass_j_msigcom,
  tm.h_m AS tmass_h_m,
  tm.h_msigcom AS tmass_h_msigcom,
  tm.ks_m AS tmass_ks_m,
  tm.ks_msigcom AS tmass_ks_msigcom
FROM gaiadr3.gaia_source AS gs
  LEFT JOIN gaiadr3.allwise_best_neighbour AS awbn ON gs.source_id = awbn.source_id
  LEFT JOIN gaiadr1.allwise_original_valid AS aw ON awbn.original_ext_source_id = aw.designation
  LEFT JOIN gaiadr3.tmass_psc_xsc_best_neighbour AS tmbn ON gs.source_id = tmbn.source_id
  LEFT JOIN gaiadr1.tmass_original_valid AS tm ON tmbn.original_ext_source_id = tm.designation
WHERE
  gs.parallax_over_error >= 5.0
  AND gs.parallax > 0
  AND gs.parallax >= 5.000000
  AND gs.parallax_error > 0
  AND gs.phot_g_mean_mag >= -10.0
  AND gs.phot_g_mean_mag <= 18.0
  AND gs.phot_bp_rp_excess_factor >= 0.0
  AND gs.phot_bp_rp_excess_factor <= 100.0
  AND gs.ruwe < 1.2
  AND gs.duplicated_source = 'false'
  AND gs.non_single_star = 0
  AND gs.classprob_dsc_combmod_galaxy < 0.1
  AND gs.classprob_dsc_combmod_quasar < 0.1
  AND ABS(gs.b) > 20.0
  AND awbn.angular_distance <= 1.5
  AND awbn.number_of_neighbours = 1
  AND awbn.number_of_mates = 0
  AND aw.designation IS NOT NULL
  AND aw.w1mpro IS NOT NULL
  AND aw.w2mpro IS NOT NULL
  AND aw.w3mpro IS NOT NULL
  AND aw.w1mpro_error > 0
  AND aw.w2mpro_error > 0
  AND aw.w3mpro_error > 0
  AND aw.w1mpro_error <= 0.217140
  AND aw.w2mpro_error <= 0.217140
  AND aw.w3mpro_error <= 0.361900
  AND (aw.cc_flags IS NULL OR aw.cc_flags = '0000')
  AND (aw.ext_flag IS NULL OR aw.ext_flag = 0)
  AND tmbn.angular_distance <= 1.5
  AND tm.designation IS NOT NULL
  AND tm.ks_m IS NOT NULL
  AND tm.ks_msigcom > 0
  AND gs.teff_gspphot >= 1.0
  AND gs.teff_gspphot <= 100000.0
  AND gs.source_id > {CURSOR_U64}
  AND gs.l >= {L_MIN}
  AND gs.l < {L_MAX}
  AND {LATITUDE_PREDICATE}
ORDER BY gs.source_id
"""

SIMBAD_QUERY: Final = "SELECT t.gaia_dr3_source_id AS gaia_dr3_source_id, b.main_id AS matched_object_id, o.otype AS matched_otype, b.ra AS matched_ra, b.dec AS matched_dec, DISTANCE(POINT('ICRS', t.ra, t.dec), POINT('ICRS', b.ra, b.dec)) * 3600.0 AS server_angular_distance_arcsec FROM TAP_UPLOAD.targets AS t JOIN basic AS b ON 1 = CONTAINS(POINT('ICRS', b.ra, b.dec), CIRCLE('ICRS', t.ra, t.dec, 0.008361111111111111)) JOIN otypes AS o ON b.oid = o.oidref WHERE o.otype IN ('AGN', 'Ae*', 'BLL', 'Bla', 'HH', 'LIN', 'Or*', 'QSO', 'Sy1', 'Sy2', 'SyG', 'TT*', 'Y*O', 'out', 'rG') ORDER BY gaia_dr3_source_id, server_angular_distance_arcsec, matched_object_id, matched_otype\n"
CHEN_DESCRIPTOR: Final = "Vizier:J/ApJS/211/25/catalog:columns=_RA,_DE,Name:row_limit=10000\n"


def render_gaia_query(cell: Cell, cursor: int, requested_rows: int) -> str:
    if cell not in CELLS:
        raise ValueError("unregistered acquisition cell")
    if type(cursor) is not int or not 0 <= cursor <= 2**63 - 1:
        raise ValueError("Gaia cursor must be an unsigned registered-range integer")
    if type(requested_rows) is not int or not 1 <= requested_rows <= SOURCE_BATCH_ROWS:
        raise ValueError("Gaia request rows outside [1,500]")
    predicate = "gs.b > 20.0" if cell.hemisphere == "north" else "gs.b < -20.0"
    replacements = {
        "{REQUEST_ROWS}": str(requested_rows),
        "{CURSOR_U64}": str(cursor),
        "{L_MIN}": f"{cell.longitude_min:.1f}",
        "{L_MAX}": f"{cell.longitude_max:.1f}",
        "{LATITUDE_PREDICATE}": predicate,
    }
    query = GAIA_QUERY_TEMPLATE
    for token, value in replacements.items():
        query = query.replace(token, value)
    if "{" in query or "}" in query or not query.endswith("\n"):
        raise AssertionError("Gaia query template substitution was incomplete")
    return query


def _exact_columns(frame: pd.DataFrame, expected: Sequence[str], context: str) -> None:
    actual = tuple(frame.columns)
    if len(actual) != len(set(actual)) or actual != tuple(expected):
        raise ValueError(f"{context}: missing, extra, duplicated, or reordered columns")


def _finite(series: pd.Series, name: str, *, nullable: bool = False) -> np.ndarray:
    if not is_float_dtype(series.dtype):
        raise TypeError(f"{name} must have float64 dtype")
    values = series.to_numpy(dtype=np.float64)
    if nullable:
        if not np.isfinite(values[~pd.isna(values)]).all():
            raise ValueError(f"{name} contains non-finite values")
    elif pd.isna(values).any() or not np.isfinite(values).all():
        raise ValueError(f"{name} contains null or non-finite values")
    return values


def _text(value: object, name: str, *, nullable: bool = False) -> str | None:
    if value is None or pd.isna(value):
        if nullable:
            return None
        raise ValueError(f"{name} is null")
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    encoded = normalized.encode("utf-8")
    if normalized != value or not encoded or len(encoded) > 512 or "\x00" in normalized:
        raise ValueError(f"{name} violates registered UTF-8 constraints")
    return normalized


def _validate_gaia_domains(frame: pd.DataFrame, cell: Cell, cursor_before: int) -> None:
    ids = frame["gaia_dr3_source_id"]
    if not is_integer_dtype(ids.dtype) or ids.isna().any():
        raise TypeError("gaia_dr3_source_id must be int64 non-null")
    id_values = ids.to_numpy(dtype=np.int64)
    if (id_values <= cursor_before).any() or (id_values <= 0).any():
        raise ValueError("Gaia source IDs regress cursor or are nonpositive")
    if len(set(int(value) for value in id_values)) != len(id_values):
        raise ValueError("Gaia source IDs must be unique")
    if len(id_values) > 1 and not (id_values[1:] > id_values[:-1]).all():
        raise ValueError("Gaia page is not strictly source-ID ascending")
    for name in (
        "ra",
        "dec",
        "galactic_l",
        "galactic_b",
        "parallax",
        "parallax_error",
        "parallax_over_error",
        "ruwe",
        "phot_g_mean_mag",
        "phot_bp_rp_excess_factor",
        "qso_probability",
        "galaxy_probability",
        "teff_gspphot",
        "wise_xm_angular_distance",
        "w1mpro",
        "w1mpro_error",
        "w1snr",
        "w2mpro",
        "w2mpro_error",
        "w2snr",
        "w3mpro",
        "w3mpro_error",
        "w3snr",
        "tmass_xm_angular_distance",
        "tmass_ks_m",
        "tmass_ks_msigcom",
    ):
        _finite(frame[name], name)
    for name in (
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
        "tmass_j_m",
        "tmass_j_msigcom",
        "tmass_h_m",
        "tmass_h_msigcom",
    ):
        _finite(frame[name], name, nullable=True)
    if not is_bool_dtype(frame["duplicated_source"].dtype):
        raise TypeError("duplicated_source must be bool")
    for name in ("non_single_star", "wise_xm_n_neighbours", "wise_xm_n_mates", "wise_xm_flag"):
        if not is_integer_dtype(frame[name].dtype) or frame[name].isna().any():
            raise TypeError(f"{name} must be int64 non-null")
    ra = frame["ra"]
    dec = frame["dec"]
    gl = frame["galactic_l"]
    gb = frame["galactic_b"]
    if ((ra < 0) | (ra >= 360) | (dec < -90) | (dec > 90)).any():
        raise ValueError("ICRS coordinate outside registered domain")
    if ((gl < cell.longitude_min) | (gl >= cell.longitude_max)).any():
        raise ValueError("Gaia row crossed its registered longitude cell")
    if cell.hemisphere == "north":
        if (gb <= 20).any():
            raise ValueError("Gaia row crossed north latitude gate")
    elif (gb >= -20).any():
        raise ValueError("Gaia row crossed south latitude gate")
    if ((gb < -90) | (gb > 90)).any():
        raise ValueError("Galactic latitude out of range")
    if (frame["parallax"] < 5).any() or (frame["parallax_error"] <= 0).any():
        raise ValueError("parallax gate violated")
    if (frame["parallax_over_error"] < 5).any():
        raise ValueError("parallax S/N gate violated")
    if ((frame["phot_g_mean_mag"] < -10) | (frame["phot_g_mean_mag"] > 18)).any():
        raise ValueError("G magnitude gate violated")
    if ((frame["phot_bp_rp_excess_factor"] < 0) | (frame["phot_bp_rp_excess_factor"] > 100)).any():
        raise ValueError("BP/RP excess domain violated")
    if (frame["ruwe"] < 0).any() or (frame["ruwe"] >= 1.2).any():
        raise ValueError("RUWE gate violated")
    if frame["duplicated_source"].any() or (frame["non_single_star"] != 0).any():
        raise ValueError("duplicated/non-single source escaped query")
    for name in ("qso_probability", "galaxy_probability"):
        if ((frame[name] < 0) | (frame[name] >= 0.1)).any():
            raise ValueError(f"{name} gate violated")
    if ((frame["teff_gspphot"] < 1) | (frame["teff_gspphot"] > 100000)).any():
        raise ValueError("temperature gate violated")
    if ((frame["wise_xm_angular_distance"] < 0) | (frame["wise_xm_angular_distance"] > 1.5)).any():
        raise ValueError("AllWISE angular-distance gate violated")
    if (frame["wise_xm_n_neighbours"] != 1).any() or (frame["wise_xm_n_mates"] != 0).any():
        raise ValueError("AllWISE multiplicity gate violated")
    if ((frame["wise_xm_flag"] < 0) | (frame["wise_xm_flag"] > 255)).any():
        raise ValueError("AllWISE xm_flag domain violated")
    if (
        (frame["tmass_xm_angular_distance"] < 0) | (frame["tmass_xm_angular_distance"] > 1.5)
    ).any():
        raise ValueError("2MASS angular-distance gate violated")
    for index, row in frame.iterrows():
        _text(row["allwise_designation"], f"allwise_designation[{index}]")
        _text(row["tmass_designation"], f"tmass_designation[{index}]")
    cc = frame["allwise_cc_flags"]
    if any(_text(value, "allwise_cc_flags", nullable=True) not in (None, "0000") for value in cc):
        raise ValueError("AllWISE cc_flags gate violated")
    ext = frame["allwise_ext_flg"]
    if any(not pd.isna(value) and int(value) != 0 for value in ext):
        raise ValueError("AllWISE ext_flg gate violated")
    for band, threshold in (("w1", 5.0), ("w2", 5.0), ("w3", 3.0)):
        mag = frame[f"{band}mpro"]
        err = frame[f"{band}mpro_error"]
        snr = frame[f"{band}snr"]
        if (
            (mag < -100) | (mag > 100) | (err <= 0) | (err > 1e6) | (snr < threshold) | (snr > 1e6)
        ).any():
            raise ValueError(f"{band.upper()} domain/SNR gate violated")
        if not np.isclose(snr, 1.0857 / err, rtol=1e-9, atol=1e-12).all():
            raise ValueError(f"forged {band.upper()} SNR")
    for band in ("j", "h"):
        mag = frame[f"tmass_{band}_m"]
        err = frame[f"tmass_{band}_msigcom"]
        present = mag.notna()
        present_error = err.notna()
        if not present.equals(present_error):
            raise ValueError(f"partial 2MASS {band.upper()} pair")
        if (
            present.any()
            and ((err[present] <= 0) | (mag[present] < -100) | (mag[present] > 100)).any()
        ):
            raise ValueError(f"invalid 2MASS {band.upper()} pair")
    if (
        (frame["tmass_ks_m"] < -100)
        | (frame["tmass_ks_m"] > 100)
        | (frame["tmass_ks_msigcom"] <= 0)
    ).any():
        raise ValueError("invalid required 2MASS Ks pair")


def _canonicalize_w4(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy(deep=True)
    columns = ["w4mpro", "w4mpro_error", "w4snr"]
    for index in result.index:
        values = [result.at[index, name] for name in columns]
        present = [not pd.isna(value) for value in values]
        for value, is_present in zip(values, present, strict=True):
            if is_present and (
                not isinstance(value, (int, float, np.number)) or not math.isfinite(float(value))
            ):
                raise ValueError("W4 contains nonnumeric or non-finite value")
        if not any(present):
            continue
        if not all(present):
            # A well-formed partial triple is registered missingness.  Any
            # present uncertainty/SNR still has to be intrinsically valid.
            if present[1] and float(values[1]) <= 0:
                raise ValueError("partial W4 has nonpositive uncertainty")
            if present[2] and float(values[2]) < 0:
                raise ValueError("partial W4 has negative SNR")
            result.loc[index, columns] = np.nan
            continue
        mag, error, snr = (float(value) for value in values)
        if not -100 <= mag <= 100 or not 0 < error <= 1e6 or not 0 <= snr <= 1e6:
            raise ValueError("W4 triple outside registered domains")
        if not math.isclose(snr, 1.0857 / error, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("forged W4 SNR")
        if snr < 2.0:
            result.loc[index, columns] = np.nan
    return result


def normalize_gaia_page(
    decoded: pd.DataFrame, *, cell: Cell, cursor_before: int, requested_rows: int
) -> pd.DataFrame:
    """Validate one complete page and canonicalize only registered W4 missingness."""
    _exact_columns(decoded, GAIA_COLUMNS, "Gaia decoded page")
    if len(decoded) != requested_rows:
        raise ValueError("Gaia short/zero/overfull page is fatal")
    _validate_gaia_domains(decoded, cell, cursor_before)
    normalized = _canonicalize_w4(decoded)
    _validate_gaia_domains(normalized, cell, cursor_before)
    w4 = normalized[["w4mpro", "w4mpro_error", "w4snr"]]
    if not (w4.isna().all(axis=1) | w4.notna().all(axis=1)).all():
        raise AssertionError("W4 canonicalization failed")
    return normalized.reset_index(drop=True)


def canonical_parent(pages: Sequence[tuple[GaiaRequestPlan, pd.DataFrame]]) -> pd.DataFrame:
    if len(pages) != GAIA_LOGICAL_REQUESTS:
        raise ValueError("canonical parent requires exactly 120 Gaia pages")
    planner = GaiaPlanner()
    tagged: list[pd.DataFrame] = []
    seen: set[int] = set()
    for plan, decoded in pages:
        normalized = normalize_gaia_page(
            decoded,
            cell=plan.cell,
            cursor_before=plan.cursor_before,
            requested_rows=plan.requested_rows,
        )
        planner = planner.accept_page(plan, normalized)
        ids = set(int(value) for value in normalized["gaia_dr3_source_id"])
        if seen.intersection(ids):
            raise ValueError("Gaia pages overlap")
        seen.update(ids)
        item = normalized.copy()
        item["__cell"] = plan.cell.ordinal
        tagged.append(item)
    parent = pd.concat(tagged, ignore_index=True).sort_values(
        ["__cell", "gaia_dr3_source_id"], kind="mergesort", ignore_index=True
    )
    parent.drop(columns=["__cell"], inplace=True)
    if len(parent) != TARGET_ROWS:
        raise ValueError("canonical parent is not 55,000 rows")
    return parent.loc[:, GAIA_COLUMNS]


def derive_bp_rp_survivors(parent: pd.DataFrame) -> pd.DataFrame:
    """Apply the registered complete-parent binary64 half-magnitude median cut."""
    _exact_columns(parent, GAIA_COLUMNS, "raw parent")
    if len(parent) != TARGET_ROWS or parent["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("BP/RP derivation requires the unique complete 55,000-row parent")
    g_values = parent["phot_g_mean_mag"].to_numpy(dtype=np.float64)
    excess = parent["phot_bp_rp_excess_factor"].to_numpy(dtype=np.float64)
    bins = np.floor(g_values * np.float64(2.0)) / np.float64(2.0)
    medians: dict[float, float] = {}
    for bin_value in sorted(set(float(value) for value in bins)):
        values = sorted(float(value) for value in excess[bins == bin_value])
        middle = len(values) // 2
        medians[bin_value] = (
            values[middle]
            if len(values) % 2
            else float((values[middle - 1] + values[middle]) / 2.0)
        )
    row_medians = np.array([medians[float(value)] for value in bins], dtype=np.float64)
    deltas = excess - row_medians
    out = parent.copy()
    out["gmag_bin_lower"] = bins
    out["bp_rp_excess_bin_median"] = row_medians
    out["bp_rp_excess_delta"] = deltas
    out = out.loc[np.abs(deltas) <= np.float64(0.1), list(BP_RP_COLUMNS)]
    return out.reset_index(drop=True)


def simbad_upload(parent_slice: pd.DataFrame) -> pd.DataFrame:
    if len(parent_slice) > SOURCE_BATCH_ROWS:
        raise ValueError("SIMBAD upload exceeds 500 rows")
    upload = parent_slice.loc[:, SIMBAD_UPLOAD_COLUMNS].copy()
    if upload["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("SIMBAD upload IDs duplicate")
    _finite(upload["ra"], "ra")
    _finite(upload["dec"], "dec")
    if (
        (upload["ra"] < 0) | (upload["ra"] >= 360) | (upload["dec"] < -90) | (upload["dec"] > 90)
    ).any():
        raise ValueError("SIMBAD upload coordinates out of domain")
    return upload.reset_index(drop=True)


def pharos_spherical_sep_arcsec_v1(
    first_ra: float, first_dec: float, second_ra: float, second_dec: float
) -> float:
    """The exact registered CPython binary64 spherical-separation function."""
    values = (first_ra, first_dec, second_ra, second_dec)
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values):
        raise ValueError("spherical coordinates must be finite numbers")
    if not 0 <= first_ra < 360 or not 0 <= second_ra < 360:
        raise ValueError("spherical RA outside [0,360)")
    if not -90 <= first_dec <= 90 or not -90 <= second_dec <= 90:
        raise ValueError("spherical Dec outside [-90,90]")
    ra1 = (float(first_ra) * PI) / 180.0
    dec1 = (float(first_dec) * PI) / 180.0
    ra2 = (float(second_ra) * PI) / 180.0
    dec2 = (float(second_dec) * PI) / 180.0
    ux = math.cos(dec1) * math.cos(ra1)
    uy = math.cos(dec1) * math.sin(ra1)
    uz = math.sin(dec1)
    vx = math.cos(dec2) * math.cos(ra2)
    vy = math.cos(dec2) * math.sin(ra2)
    vz = math.sin(dec2)
    cx = uy * vz - uz * vy
    cy = uz * vx - ux * vz
    cz = ux * vy - uy * vx
    cross_norm = math.sqrt(cx * cx + cy * cy + cz * cz)
    dot_unclamped = ux * vx + uy * vy + uz * vz
    dot = min(1.0, max(-1.0, dot_unclamped))
    separation = math.atan2(cross_norm, dot) * (180.0 / PI) * 3600.0
    return float(separation)


def normalize_simbad_exclusions(
    raw: pd.DataFrame, upload: pd.DataFrame, bp_rp_parent: pd.DataFrame
) -> pd.DataFrame:
    _exact_columns(raw, SIMBAD_RAW_COLUMNS, "SIMBAD decoded raw")
    _exact_columns(upload, SIMBAD_UPLOAD_COLUMNS, "SIMBAD upload")
    if len(raw) >= SIMBAD_MAXREC:
        raise ValueError("SIMBAD truncation sentinel reached")
    requested = set(int(value) for value in upload["gaia_dr3_source_id"])
    positions = {
        int(row.gaia_dr3_source_id): (float(row.ra), float(row.dec))
        for row in upload.itertuples(index=False)
    }
    parent_rank = {
        int(value): index for index, value in enumerate(bp_rp_parent["gaia_dr3_source_id"])
    }
    discovered: dict[int, int] = {}
    records: list[dict[str, object]] = []
    for row in raw.itertuples(index=False):
        source_id = int(row.gaia_dr3_source_id)
        if source_id not in requested:
            raise ValueError("SIMBAD returned unrequested source ID")
        discovered[source_id] = discovered.get(source_id, 0) + 1
        if discovered[source_id] > MAX_MATCHES_PER_SOURCE_CATALOG:
            raise ValueError("SIMBAD discovered-match bound exceeded")
        object_id = _text(row.matched_object_id, "matched_object_id")
        object_type = _text(row.matched_otype, "matched_otype")
        if object_type not in SIMBAD_TYPES:
            raise ValueError("unregistered SIMBAD object type")
        matched_ra = float(row.matched_ra)
        matched_dec = float(row.matched_dec)
        server_sep = float(row.server_angular_distance_arcsec)
        if not all(math.isfinite(v) for v in (matched_ra, matched_dec, server_sep)):
            raise ValueError("SIMBAD numeric value non-finite")
        if (
            not 0 <= matched_ra < 360
            or not -90 <= matched_dec <= 90
            or not 0 <= server_sep <= SIMBAD_DISCOVERY_RADIUS_ARCSEC
        ):
            raise ValueError("SIMBAD discovery value out of domain")
        source_ra, source_dec = positions[source_id]
        local = pharos_spherical_sep_arcsec_v1(source_ra, source_dec, matched_ra, matched_dec)
        if local <= EXCLUSION_RADIUS_ARCSEC:
            records.append(
                {
                    "gaia_dr3_source_id": source_id,
                    "exclusion_catalog": "SIMBAD",
                    "exclusion_class": "YSO" if object_type in SIMBAD_YSO_TYPES else "AGN",
                    "matched_object_id": object_id,
                    "matched_otype": object_type,
                    "angular_distance_arcsec": local,
                    "catalog_release": SIMBAD_RELEASE,
                }
            )
    records.sort(
        key=lambda item: (
            parent_rank[cast(int, item["gaia_dr3_source_id"])],
            cast(float, item["angular_distance_arcsec"]),
            str(item["matched_object_id"]).encode(),
            str(item["matched_otype"]).encode(),
        )
    )
    unique: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    retained: dict[int, int] = {}
    for item in records:
        identity = tuple(item[column] for column in EXCLUSION_COLUMNS)
        if identity in seen:
            continue
        seen.add(identity)
        source_id = cast(int, item["gaia_dr3_source_id"])
        retained[source_id] = retained.get(source_id, 0) + 1
        if retained[source_id] > MAX_MATCHES_PER_SOURCE_CATALOG:
            raise ValueError("SIMBAD retained-match bound exceeded")
        unique.append(item)
    return pd.DataFrame(unique, columns=EXCLUSION_COLUMNS)


def validate_chen_raw(raw: pd.DataFrame) -> pd.DataFrame:
    _exact_columns(raw, CHEN_RAW_COLUMNS, "Chen decoded raw")
    if len(raw) >= CHEN_ROW_LIMIT:
        raise ValueError("Chen truncation limit reached")
    _finite(raw["_RA"], "_RA")
    _finite(raw["_DE"], "_DE")
    if ((raw["_RA"] < 0) | (raw["_RA"] >= 360) | (raw["_DE"] < -90) | (raw["_DE"] > 90)).any():
        raise ValueError("Chen coordinates outside registered domains")
    indexes = raw["_raw_row_index"]
    if not is_integer_dtype(indexes.dtype) or list(indexes.astype(int)) != list(range(len(raw))):
        raise ValueError("Chen raw-row index is not contiguous from zero")
    for value in raw["Name"]:
        _text(value, "Chen Name")
    return raw


def match_chen_exclusions(raw: pd.DataFrame, bp_rp_parent: pd.DataFrame) -> pd.DataFrame:
    validate_chen_raw(raw)
    _exact_columns(bp_rp_parent, BP_RP_COLUMNS, "BP/RP parent")
    records: list[dict[str, object]] = []
    for source in bp_rp_parent.itertuples(index=False):
        per_source: list[tuple[float, bytes, int, dict[str, object]]] = []
        for chen_ra, chen_dec, chen_name, raw_row_index in raw.itertuples(
            index=False, name=None
        ):
            separation = pharos_spherical_sep_arcsec_v1(
                float(source.ra), float(source.dec), float(chen_ra), float(chen_dec)
            )
            if separation <= EXCLUSION_RADIUS_ARCSEC:
                item = {
                    "gaia_dr3_source_id": int(source.gaia_dr3_source_id),
                    "exclusion_catalog": "Chen2014",
                    "exclusion_class": "debris_disk",
                    "matched_object_id": str(chen_name),
                    "matched_otype": "debris_disk",
                    "angular_distance_arcsec": separation,
                    "catalog_release": CHEN_RELEASE,
                }
                per_source.append(
                    (separation, str(chen_name).encode(), int(raw_row_index), item)
                )
        if len(per_source) > MAX_MATCHES_PER_SOURCE_CATALOG:
            raise ValueError("Chen per-source/catalog match bound exceeded")
        per_source.sort(key=lambda value: (value[0], value[1], value[2]))
        records.extend(item for _, _, _, item in per_source)
    return pd.DataFrame(records, columns=EXCLUSION_COLUMNS)


def normalize_exclusions(
    simbad_parts: Iterable[pd.DataFrame], chen: pd.DataFrame, bp_rp_parent: pd.DataFrame
) -> pd.DataFrame:
    parts = [part for part in simbad_parts]
    combined = (
        pd.concat([*parts, chen], ignore_index=True)
        if parts or not chen.empty
        else pd.DataFrame(columns=EXCLUSION_COLUMNS)
    )
    _exact_columns(combined, EXCLUSION_COLUMNS, "normalized exclusions")
    if combined.duplicated(list(EXCLUSION_COLUMNS)).any():
        raise ValueError("residual exact exclusion duplicate")
    ranks = {int(value): index for index, value in enumerate(bp_rp_parent["gaia_dr3_source_id"])}
    if not set(combined["gaia_dr3_source_id"].astype(int)).issubset(ranks):
        raise ValueError("exclusion ID is outside BP/RP parent")
    catalog_order = {"SIMBAD": 0, "Chen2014": 1}
    rows = combined.to_dict("records")
    rows.sort(
        key=lambda item: (
            ranks[int(item["gaia_dr3_source_id"])],
            catalog_order[str(item["exclusion_catalog"])],
            float(item["angular_distance_arcsec"]),
            str(item["matched_object_id"]).encode(),
            str(item["matched_otype"]).encode(),
        )
    )
    return pd.DataFrame(rows, columns=EXCLUSION_COLUMNS)


def derive_quiet_negative(bp_rp: pd.DataFrame, exclusions: pd.DataFrame) -> pd.DataFrame:
    _exact_columns(bp_rp, BP_RP_COLUMNS, "BP/RP survivors")
    _exact_columns(exclusions, EXCLUSION_COLUMNS, "exclusions")
    if bp_rp["gaia_dr3_source_id"].duplicated().any():
        raise ValueError("duplicate BP/RP source IDs")
    excluded = set(int(value) for value in exclusions["gaia_dr3_source_id"])
    parent = set(int(value) for value in bp_rp["gaia_dr3_source_id"])
    if not excluded.issubset(parent):
        raise ValueError("exclusion IDs outside BP/RP parent")
    controls = bp_rp.loc[~bp_rp["gaia_dr3_source_id"].isin(excluded), list(BP_RP_COLUMNS)].copy()
    controls.reset_index(drop=True, inplace=True)
    if len(controls) != len(bp_rp) - len(excluded):
        raise AssertionError("final difference mismatch")
    if not 50_000 <= len(controls) <= 250_000:
        raise ValueError("final control count fails bounds")
    represented: set[int] = set()
    for row in controls.itertuples(index=False):
        for cell in CELLS:
            if cell.longitude_min <= row.galactic_l < cell.longitude_max and (
                (cell.hemisphere == "north" and row.galactic_b > 20)
                or (cell.hemisphere == "south" and row.galactic_b < -20)
            ):
                represented.add(cell.ordinal)
                break
    if represented != set(range(CELL_COUNT)):
        raise ValueError("a registered cell has no final row")
    return controls

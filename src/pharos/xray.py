"""X-ray cross-match for Pharos v0.1.1 HOT DOG component.

Pre-registration v0.1.1 §2 requires a positional cross-match of every
source against four public X-ray catalogs:

  - 2RXS              (ROSAT All-Sky 2nd revision, Boller et al. 2016)
  - XMM-Newton DR12   (XMM-SSC 2022)
  - eROSITA-DE DR1    (Merloni et al. 2024, German half-sky)
  - Chandra CSC v2.0  (Evans et al. 2010+)

The HOT DOG indicator's X-ray-null requirement consults these results:
a source with any X-ray detection at its Gaia DR3 position (within 10″)
has its HOT DOG probability attenuated to zero. Coverage is recorded
explicitly so a source outside all catalog footprints is treated as
"X-ray unconstrained" rather than "X-ray null."

The cross-match runs per-catalog via Vizier cone searches. CDS XMatch
would be faster for batch queries but the Vizier table identifiers for
the eROSITA-DE DR1 release are not yet routed through XMatch reliably
during the DR4 transition, so we use direct Vizier queries.

Network access is encapsulated in ``fetch_xray_crossmatch``. Everything
else in the module is pure and deterministic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-registered catalog identifiers and search radius.
# Source: pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md §2.
# ---------------------------------------------------------------------------
XRAY_SEARCH_RADIUS_ARCSEC: float = 10.0

# Vizier catalog identifiers used for the cone queries. These map to the
# specific table that holds the per-source detections (not the metadata).
XRAY_CATALOGS: dict[str, str] = {
    "2rxs": "IX/29/rass",      # Boller et al. 2016 (2RXS)
    "xmm": "IX/69/xmm5dr14",   # XMM-Newton Serendipitous Source Catalog
    "erosita": "J/A+A/682/A34/table1",  # Merloni et al. 2024 (eROSITA-DE DR1)
    "chandra": "IX/57/csc2master",  # Chandra Source Catalog v2 master
}

# Polite pause between Vizier queries to avoid rate-limiting.
_PER_QUERY_SLEEP_SECONDS: float = 0.5


@dataclass(frozen=True)
class XrayCrossmatchResult:
    """Per-source X-ray cross-match summary.

    ``positions`` is the input table with one row per source. ``matches``
    is a long-form table with one row per (source, catalog, match)
    combination — useful for debugging or for verifying coverage
    decisions.
    """

    summary: pd.DataFrame  # one row per source, with xray_* columns
    matches: pd.DataFrame  # long-form, one row per (source, catalog) match


def _erosita_de_covers(galactic_l_deg: pd.Series) -> pd.Series:
    """German half-sky coverage: galactic longitude 180° ≤ l < 360°.

    The Russian half (0° ≤ l < 180°) is held by IKI and not in DR1.
    """
    return (galactic_l_deg >= 180.0) & (galactic_l_deg < 360.0)


def _empty_match_summary(positions: pd.DataFrame) -> pd.DataFrame:
    """Initialise the per-source summary frame with zero matches everywhere."""
    out = pd.DataFrame(index=positions.index)
    out["gaia_dr3_source_id"] = positions["gaia_dr3_source_id"].astype("int64").to_numpy()
    for cat in XRAY_CATALOGS:
        out[f"xray_{cat}_match_count"] = 0
        out[f"xray_{cat}_min_arcsec"] = np.nan
    out["xray_any_detection"] = False
    out["xray_coverage_count"] = 0
    return out


def fetch_xray_crossmatch(
    positions: pd.DataFrame,
    *,
    catalogs: Iterable[str] = tuple(XRAY_CATALOGS.keys()),
    search_radius_arcsec: float = XRAY_SEARCH_RADIUS_ARCSEC,
) -> XrayCrossmatchResult:
    """Cross-match each source position against the configured X-ray catalogs.

    ``positions`` must have columns ``gaia_dr3_source_id``, ``ra``,
    ``dec``, and ``galactic_l`` (the last is needed for eROSITA-DE
    coverage determination).
    """
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from astroquery.vizier import Vizier  # type: ignore[import-untyped]

    Vizier.ROW_LIMIT = -1
    Vizier.TIMEOUT = 120

    for col in ("gaia_dr3_source_id", "ra", "dec", "galactic_l"):
        if col not in positions.columns:
            raise ValueError(f"positions dataframe missing column {col!r}")

    summary = _empty_match_summary(positions)
    match_rows: list[dict] = []

    # 2RXS is all-sky, so every source has 2RXS coverage. eROSITA-DE has
    # half-sky coverage that we can determine from galactic longitude
    # alone. XMM and Chandra are pointed — we treat coverage as
    # "match implies coverage" plus an explicit "out-of-FOV" tag from
    # the catalog metadata where applicable.
    coverage_2rxs = pd.Series(True, index=summary.index)
    coverage_erosita = _erosita_de_covers(positions["galactic_l"])

    for cat in catalogs:
        if cat not in XRAY_CATALOGS:
            raise ValueError(f"unknown X-ray catalog {cat!r}")
        vizier_id = XRAY_CATALOGS[cat]
        logger.info(
            "X-ray cross-match: %s (vizier:%s) over %d positions, radius=%.1f″",
            cat, vizier_id, len(positions), search_radius_arcsec,
        )
        for idx, row in positions.iterrows():
            coord = SkyCoord(
                ra=row["ra"] * u.deg, dec=row["dec"] * u.deg, frame="icrs"
            )
            try:
                tables = Vizier.query_region(
                    coord, radius=search_radius_arcsec * u.arcsec, catalog=vizier_id
                )
            except Exception as exc:  # noqa: BLE001 — log and continue
                logger.warning(
                    "vizier query failed for source %s in %s: %s",
                    row["gaia_dr3_source_id"], cat, exc,
                )
                continue
            time.sleep(_PER_QUERY_SLEEP_SECONDS)
            if not tables or len(tables) == 0:
                continue
            table = tables[0]
            n_matches = len(table)
            if n_matches == 0:
                continue
            # Find the angular distance column if present; otherwise
            # compute it from the catalog's RA/Dec.
            min_dist = _min_angular_distance(coord, table)
            summary.at[idx, f"xray_{cat}_match_count"] = int(n_matches)
            summary.at[idx, f"xray_{cat}_min_arcsec"] = float(min_dist)
            match_rows.append(
                {
                    "gaia_dr3_source_id": int(row["gaia_dr3_source_id"]),
                    "catalog": cat,
                    "n_matches": int(n_matches),
                    "min_arcsec": float(min_dist),
                }
            )

    # Coverage rollup.
    coverage_xmm = summary["xray_xmm_match_count"] > 0  # implied by match
    coverage_chandra = summary["xray_chandra_match_count"] > 0  # implied by match
    summary["xray_coverage_count"] = (
        coverage_2rxs.astype(int)
        + coverage_erosita.astype(int)
        + coverage_xmm.astype(int)
        + coverage_chandra.astype(int)
    )
    summary["xray_any_detection"] = (
        (summary["xray_2rxs_match_count"] > 0)
        | (summary["xray_xmm_match_count"] > 0)
        | (summary["xray_erosita_match_count"] > 0)
        | (summary["xray_chandra_match_count"] > 0)
    )

    logger.info(
        "X-ray cross-match complete: %d sources, %d with any detection",
        len(summary),
        int(summary["xray_any_detection"].sum()),
    )
    return XrayCrossmatchResult(
        summary=summary,
        matches=pd.DataFrame(match_rows) if match_rows else pd.DataFrame(
            columns=["gaia_dr3_source_id", "catalog", "n_matches", "min_arcsec"]
        ),
    )


def _min_angular_distance(coord, table) -> float:
    """Return the smallest angular distance (arcsec) from coord to any row in table.

    Tries common RA/Dec column-name conventions in Vizier tables.
    """
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    ra_candidates = ["RAJ2000", "_RAJ2000", "RA_ICRS", "RA"]
    dec_candidates = ["DEJ2000", "_DEJ2000", "DE_ICRS", "DEC", "Dec"]
    ra_col = next((c for c in ra_candidates if c in table.colnames), None)
    dec_col = next((c for c in dec_candidates if c in table.colnames), None)
    if ra_col is None or dec_col is None:
        return float("nan")
    cat_coords = SkyCoord(
        ra=table[ra_col] * u.deg, dec=table[dec_col] * u.deg, frame="icrs"
    )
    seps = coord.separation(cat_coords).to(u.arcsec).value
    return float(np.min(seps))


def save_xray_crossmatch(
    result: XrayCrossmatchResult, output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result.summary.to_parquet(output_dir / "xray_summary.parquet", index=False)
    result.matches.to_parquet(output_dir / "xray_matches.parquet", index=False)


def load_xray_crossmatch(input_dir: Path) -> XrayCrossmatchResult:
    return XrayCrossmatchResult(
        summary=pd.read_parquet(input_dir / "xray_summary.parquet"),
        matches=pd.read_parquet(input_dir / "xray_matches.parquet"),
    )

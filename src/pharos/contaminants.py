"""Contaminant-positive control set fetcher for Pharos v0.1.1.

Pre-registration v0.1.1 §1 fixes the contaminant-positive set composition:

  - Hephaistos confirmed + suspected (G, A, B)         — local registry
  - Million Quasars (Flesch 2023, v8.0)                — Vizier VII/290
  - Marton et al. 2019 Gaia DR2 YSO probability ≥ 0.8  — Vizier J/MNRAS/487/2522
  - Chen et al. 2014 debris disks                      — Vizier J/ApJS/211/25

Every contaminant must additionally:
  - Satisfy the v0.1 WISE-only coverage class (pre-reg v0.1 §2)
  - Have a 2MASS counterpart within 1.5″
  - **Not** be in the quiet-negative population

Each sub-population's actual count is recorded in
``controls/contaminant_positive/manifest.yaml`` because the v0.1
coverage class is highly selective for some catalogs (Million Quasars
in particular has almost no entries with positive parallax).

Network access is in ``fetch_contaminants_positive``. Pure helpers are
deterministic and unit-testable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pharos import sources

logger = logging.getLogger(__name__)

# Vizier table identifiers per pre-reg v0.1.1 §1.1.
MILLION_QUASARS_VIZIER = "VII/290/catalog"
MARTON_YSO_VIZIER = "II/360/catalog"  # Gaia DR2 x AllWISE YSO classification
CHEN_DEBRIS_VIZIER = "J/ApJS/211/25"  # Chen et al. 2014, main catalog table

# Polite pause between Vizier downloads.
_PER_CATALOG_SLEEP_SECONDS: float = 1.0

# Crossmatch radius for catalog-to-Gaia matching. Looser than the X-ray
# radius because optical/IR positions are precise; we want to be sure
# we have the right Gaia source for any reasonable catalog entry.
_GAIA_XMATCH_RADIUS_ARCSEC: float = 2.0


@dataclass(frozen=True)
class ContaminantFetchResult:
    """The combined contaminant_positive set plus per-source provenance."""

    sources: pd.DataFrame  # full join: gaia + allwise + 2mass + sub_population
    manifest: dict  # counts per sub-population + filtering provenance


def _coverage_class_filter(df: pd.DataFrame) -> pd.Series:
    """Boolean mask for v0.1 WISE-only coverage class."""
    cov = sources.COVERAGE_CLASS_CUTS
    return (
        (df["parallax_over_error"] >= cov["parallax_over_error_min"])
        & (df["parallax"] > 0)
        & (df["parallax"] >= 1000.0 / cov["distance_pc_max"])
        & (df["phot_g_mean_mag"] <= cov["g_mag_max"])
        & (df["wise_xm_angular_distance"] <= cov["allwise_angular_distance_max_arcsec"])
        & (df["w1mpro_error"] <= 1.0857 / cov["w1_snr_min"])
        & (df["w2mpro_error"] <= 1.0857 / cov["w2_snr_min"])
        & (df["w3mpro_error"] <= 1.0857 / cov["w3_snr_min"])
        & (df["tmass_xm_angular_distance"].notna())
        & (df["tmass_xm_angular_distance"] <= 1.5)
    )


def _crossmatch_positions_to_gaia(
    ra: np.ndarray, dec: np.ndarray, radius_arcsec: float = _GAIA_XMATCH_RADIUS_ARCSEC
) -> list[int]:
    """Batch-crossmatch (ra, dec) positions to Gaia DR3 via CDS XMatch.

    CDS XMatch is a stable, independent service (cdsxmatch.cds.unistra.fr)
    specifically designed for batch positional crossmatch against any
    Vizier-hosted catalog. We use it in preference to the Gaia archive's
    TAP-Upload mechanism, which has been consistently aborting our
    upload jobs during the DR4 transition.
    """
    if len(ra) == 0:
        return []

    from astropy import units as u  # type: ignore[import-untyped]
    from astropy.table import Table  # type: ignore[import-untyped]
    from astroquery.xmatch import XMatch  # type: ignore[import-untyped]

    table = Table({"idx": np.arange(len(ra)), "ra": ra.astype(float), "dec": dec.astype(float)})
    logger.info(
        "CDS XMatch %d positions against Gaia DR3 (radius=%.1f arcsec)",
        len(ra), radius_arcsec,
    )
    try:
        result = XMatch.query(
            cat1=table,
            cat2="vizier:I/355/gaiadr3",
            max_distance=radius_arcsec * u.arcsec,
            colRA1="ra",
            colDec1="dec",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("CDS XMatch query failed: %s", exc)
        return []

    if len(result) == 0:
        logger.info("CDS XMatch returned 0 matches")
        return []
    df = result.to_pandas()
    # CDS XMatch returns columns named after the second catalog's
    # source identifier; for Gaia DR3 it's typically `Source` or
    # `source_id`. Pick whichever is present.
    id_col = next(
        (c for c in ("source_id", "Source", "DR3Name", "SourceID")
         if c in df.columns),
        None,
    )
    if id_col is None:
        logger.error(
            "CDS XMatch response missing Gaia DR3 ID column; got %s", list(df.columns)
        )
        return []
    dist_col = next(
        (c for c in ("angDist", "dist", "angular_distance") if c in df.columns),
        None,
    )
    # Keep the nearest match per upload row.
    if dist_col is not None and "idx" in df.columns:
        df = df.sort_values(["idx", dist_col]).drop_duplicates("idx", keep="first")
    matched_ids = df[id_col].astype("int64").tolist()
    logger.info("CDS XMatch returned %d unique Gaia DR3 matches", len(matched_ids))
    return matched_ids


def _vizier_query_all(catalog_id: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Pull all rows from a Vizier catalog. Use sparingly — large catalogs
    benefit from positional cone searches instead, but our contaminant
    catalogs are small or well-indexed."""
    from astroquery.vizier import Vizier  # type: ignore[import-untyped]

    Vizier.ROW_LIMIT = -1
    Vizier.TIMEOUT = 600
    if columns:
        Vizier.columns = columns
    logger.info("downloading Vizier catalog %s", catalog_id)
    tables = Vizier.get_catalogs(catalog_id)
    if not tables or len(tables) == 0:
        return pd.DataFrame()
    return tables[0].to_pandas()


def fetch_hephaistos_contaminants(
    hephaistos_yaml: Path, join_cache: Path
) -> tuple[pd.DataFrame, dict]:
    """Pull the labelled Hephaistos contaminants out of the registry."""
    import yaml

    registry = yaml.safe_load(open(hephaistos_yaml, encoding="utf-8"))
    join_df = pd.read_parquet(join_cache)

    label_to_status = {c["label"]: c["status"] for c in registry["candidates"]}
    join_df = join_df.copy()
    join_df["sub_population"] = "hephaistos"
    join_df["contaminant_label"] = join_df["hephaistos_label"]

    keep_statuses = {"contaminant_confirmed", "contaminant_suspected"}
    keep_labels = {label for label, st in label_to_status.items() if st in keep_statuses}
    out = join_df[join_df["hephaistos_label"].isin(keep_labels)].copy()
    manifest = {
        "source": "controls/hephaistos.yaml",
        "kept_labels": sorted(keep_labels),
        "n_kept": int(len(out)),
    }
    return out, manifest


def fetch_marton_ysos(
    min_yso_prob: float = 0.8,
    max_count_for_xmatch: int = 5000,
) -> tuple[list[int], dict]:
    """Pull Marton et al. 2019 YSO catalog (server-side SY filter), then
    batch-crossmatch RA/Dec to Gaia DR3.

    The catalog provides Gaia DR2 IDs; we crossmatch by position so we
    don't have to maintain a separate DR2→DR3 ID translation table.
    """
    from astroquery.vizier import Vizier  # type: ignore[import-untyped]

    # Server-side filter: SY ≥ min_yso_prob. Without this, the
    # ROW_LIMIT=-1 download would try to pull all ~80M Gaia x AllWISE
    # rows, which is intractable.
    v = Vizier(
        columns=["Source", "RA_ICRS", "DE_ICRS", "SY"],
        column_filters={"SY": f">={min_yso_prob}"},
        row_limit=max_count_for_xmatch,
        timeout=300,
    )
    logger.info("downloading Marton 2019 YSO (SY >= %.2f, cap %d)", min_yso_prob, max_count_for_xmatch)
    tables = v.get_catalogs(MARTON_YSO_VIZIER)
    if not tables or len(tables) == 0:
        return [], {"source": MARTON_YSO_VIZIER, "n_kept": 0}
    df = tables[0].to_pandas()
    if len(df) == 0 or "SY" not in df.columns:
        return [], {"source": MARTON_YSO_VIZIER, "n_kept": 0, "error": "empty after SY filter"}

    ra_col = next((c for c in ("RA_ICRS", "RAJ2000", "_RAJ2000", "_RA") if c in df.columns), None)
    dec_col = next((c for c in ("DE_ICRS", "DEJ2000", "_DEJ2000", "_DE") if c in df.columns), None)
    if ra_col is None or dec_col is None:
        logger.warning("Marton YSO catalog: no RA/Dec columns")
        return [], {"source": MARTON_YSO_VIZIER, "n_kept": 0, "error": "no RA/Dec columns"}

    matched = _crossmatch_positions_to_gaia(df[ra_col].to_numpy(), df[dec_col].to_numpy())
    return matched, {
        "source": MARTON_YSO_VIZIER,
        "min_yso_prob": min_yso_prob,
        "n_from_catalog": int(len(df)),
        "n_xmatched_to_gaia": int(len(matched)),
    }


def fetch_chen_debris_disks() -> tuple[list[int], dict]:
    """Pull Chen et al. 2014 debris disks, crossmatch to Gaia DR3."""
    df = _vizier_query_all(CHEN_DEBRIS_VIZIER, columns=["**"])
    if len(df) == 0:
        return [], {"source": CHEN_DEBRIS_VIZIER, "n_kept": 0}

    ra_col = next((c for c in ("RA_ICRS", "RAJ2000", "_RAJ2000", "_RA") if c in df.columns), None)
    dec_col = next((c for c in ("DE_ICRS", "DEJ2000", "_DEJ2000", "_DE") if c in df.columns), None)
    if ra_col is None or dec_col is None:
        return [], {"source": CHEN_DEBRIS_VIZIER, "n_kept": 0, "error": "no RA/Dec columns"}

    matched = _crossmatch_positions_to_gaia(df[ra_col].to_numpy(), df[dec_col].to_numpy())
    return matched, {
        "source": CHEN_DEBRIS_VIZIER,
        "n_from_catalog": int(len(df)),
        "n_xmatched_to_gaia": int(len(matched)),
    }


def fetch_million_quasars() -> tuple[list[int], dict]:
    """Pull Million Quasars Catalogue (Flesch v8.0), crossmatch to Gaia DR3.

    Almost no entries will satisfy the v0.1 coverage class (positive
    parallax + distance ≤ 200 pc); QSOs are extragalactic. We pull only
    bright-flag entries to keep the volume tractable. Final count
    almost always falls back near zero — recorded faithfully in the
    manifest.
    """
    from astroquery.vizier import Vizier  # type: ignore[import-untyped]

    Vizier.ROW_LIMIT = 50000  # cap; Flesch is ~7M rows total
    Vizier.TIMEOUT = 600
    Vizier.columns = ["**"]
    logger.info("downloading Million Quasars catalog (capped at 50k rows)")
    tables = Vizier.get_catalogs(MILLION_QUASARS_VIZIER)
    if not tables or len(tables) == 0:
        return [], {"source": MILLION_QUASARS_VIZIER, "n_kept": 0}
    df = tables[0].to_pandas()
    # Keep only bright entries (lower magnitudes) where Gaia DR3 may
    # actually have a (spurious) match.
    mag_col = next((c for c in ("RMAG", "Rmag", "Gmag") if c in df.columns), None)
    if mag_col is not None:
        df = df[df[mag_col] <= 20.0]
    ra_col = next((c for c in ("RAJ2000", "_RAJ2000", "RA_ICRS") if c in df.columns), None)
    dec_col = next((c for c in ("DEJ2000", "_DEJ2000", "DE_ICRS") if c in df.columns), None)
    if ra_col is None or dec_col is None:
        return [], {"source": MILLION_QUASARS_VIZIER, "n_kept": 0, "error": "no RA/Dec"}
    matched = _crossmatch_positions_to_gaia(df[ra_col].to_numpy()[:1000], df[dec_col].to_numpy()[:1000])
    return matched, {
        "source": MILLION_QUASARS_VIZIER,
        "n_from_catalog_capped": int(len(df)),
        "n_attempted_xmatch": min(1000, int(len(df))),
        "n_xmatched_to_gaia": int(len(matched)),
    }


def fetch_contaminants_positive(
    hephaistos_yaml: Path,
    hephaistos_join_cache: Path,
    quiet_negative_cache: Path,
    output_dir: Path,
    *,
    skip_million_quasars: bool = False,
) -> ContaminantFetchResult:
    """Build the full contaminant_positive set per pre-reg v0.1.1 §1."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Hephaistos labelled contaminants.
    heph_df, heph_manifest = fetch_hephaistos_contaminants(
        hephaistos_yaml, hephaistos_join_cache
    )

    # 2-4. Sub-population Gaia IDs from external catalogs.
    sub_pops: list[tuple[str, list[int], dict]] = []
    yso_ids, yso_manifest = fetch_marton_ysos()
    sub_pops.append(("marton_yso", yso_ids, yso_manifest))
    time.sleep(_PER_CATALOG_SLEEP_SECONDS)

    debris_ids, debris_manifest = fetch_chen_debris_disks()
    sub_pops.append(("chen_debris", debris_ids, debris_manifest))
    time.sleep(_PER_CATALOG_SLEEP_SECONDS)

    qso_ids: list[int] = []
    qso_manifest: dict = {"source": MILLION_QUASARS_VIZIER, "skipped": skip_million_quasars}
    if not skip_million_quasars:
        qso_ids, qso_manifest = fetch_million_quasars()
    sub_pops.append(("million_quasars", qso_ids, qso_manifest))

    # 5. Pull the full Gaia + AllWISE + 2MASS join for these IDs, apply
    # the v0.1 coverage class filter, exclude any source that's already
    # in the quiet-negative population.
    all_external_ids = sorted({sid for _, ids, _ in sub_pops for sid in ids})
    join_rows: list[pd.DataFrame] = []
    if all_external_ids:
        logger.info(
            "fetching Gaia + AllWISE + 2MASS join for %d external contaminants",
            len(all_external_ids),
        )
        join_result = sources.fetch_targets_by_source_id(
            all_external_ids, cache_path=None, use_cache=False
        )
        join_df = join_result.sources.copy()
        # Tag each source with its sub-population (a source can be in
        # multiple — use the first one).
        sub_pop_map: dict[int, str] = {}
        for name, ids, _ in sub_pops:
            for sid in ids:
                sub_pop_map.setdefault(sid, name)
        join_df["sub_population"] = join_df["gaia_dr3_source_id"].map(sub_pop_map)
        join_df["contaminant_label"] = pd.NA
        join_rows.append(join_df)

    # Hephaistos sources go in as their own rows.
    join_rows.append(heph_df)
    combined = pd.concat(join_rows, ignore_index=True) if join_rows else pd.DataFrame()

    # Coverage filter.
    pre_count = len(combined)
    mask = _coverage_class_filter(combined)
    in_cov = combined[mask].copy()
    in_cov_count = len(in_cov)

    # Exclude any source that's also in the quiet-negative population.
    if quiet_negative_cache.exists():
        qn_ids = set(
            pd.read_parquet(quiet_negative_cache)["gaia_dr3_source_id"]
            .astype("int64")
            .tolist()
        )
        in_cov = in_cov[~in_cov["gaia_dr3_source_id"].isin(qn_ids)].copy()
    final_count = len(in_cov)

    manifest = {
        "spec": "pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md §1",
        "sub_populations": {
            "hephaistos": heph_manifest,
            "marton_yso": yso_manifest,
            "chen_debris": debris_manifest,
            "million_quasars": qso_manifest,
        },
        "totals": {
            "n_pre_coverage_filter": int(pre_count),
            "n_after_coverage_filter": int(in_cov_count),
            "n_after_quiet_negative_exclusion": int(final_count),
        },
    }
    logger.info("contaminant_positive set: %d sources after all filters", final_count)
    return ContaminantFetchResult(sources=in_cov, manifest=manifest)

"""Command-line entry points for Pharos data fetches.

Two subcommands are provided:

    python -m pharos.cli fetch_quiet_negative \\
        --output controls/cache/quiet_negative.parquet \\
        --limit 100000

    python -m pharos.cli fetch_hephaistos \\
        --registry controls/hephaistos.yaml \\
        --output controls/cache/hephaistos_join.parquet

Both submit pre-registered ADQL to the Gaia archive (gea.esac.esa.int)
and cache the results to parquet. The ``fetch_hephaistos`` command also
merges in W1↔W3 photocentre offsets and other per-candidate fields from
``controls/hephaistos.yaml`` (Suazo et al. 2024 Table 5 / Table 7), so
the resulting parquet has every column the v0.1 scoring pipeline needs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

from pharos import sources

logger = logging.getLogger("pharos.cli")

# Keys in the Hephaistos registry that, when present and non-null, should be
# merged into the join dataframe. Mapped to the column name used downstream
# (which must match what the scoring modules expect — see ``confounders.py``).
_REGISTRY_OVERRIDE_COLUMNS: dict[str, str] = {
    "w1_w2_offset_arcsec_ra": "w1_w2_offset_arcsec_ra",
    "w1_w2_offset_arcsec_dec": "w1_w2_offset_arcsec_dec",
    "w1_w3_offset_arcsec_ra": "w1_w3_offset_arcsec_ra",
    "w1_w3_offset_arcsec_dec": "w1_w3_offset_arcsec_dec",
    "iris_100um_mjy_sr": "iris_100um_mjy_sr",
}


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING - 10 * verbosity
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_fetch_quiet_negative(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    logger.info("fetching quiet-negative controls -> %s (limit=%s)", output, args.limit)
    result = sources.fetch_quiet_negative_controls(
        cache_path=output, limit=args.limit, use_cache=not args.force_refresh
    )
    logger.info(
        "quiet-negative cache ready: %d rows (query hash %s)",
        result.n_sources,
        result.query_hash[:12],
    )
    return 0


def _load_registry(registry_path: Path) -> dict:
    with open(registry_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_candidate_overrides(registry: dict) -> pd.DataFrame:
    rows: list[dict] = []
    for cand in registry.get("candidates", []):
        sid = cand.get("gaia_dr3_source_id")
        if sid is None:
            continue
        row: dict = {"gaia_dr3_source_id": int(sid), "hephaistos_label": cand.get("label")}
        for src_key, dst_col in _REGISTRY_OVERRIDE_COLUMNS.items():
            row[dst_col] = cand.get(src_key)
        rows.append(row)
    return pd.DataFrame(rows)


def cmd_fetch_hephaistos(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry).resolve()
    output = Path(args.output).resolve()
    registry = _load_registry(registry_path)
    overrides = _extract_candidate_overrides(registry)
    source_ids = overrides["gaia_dr3_source_id"].tolist()
    if not source_ids:
        logger.error("no Gaia DR3 source IDs found in %s", registry_path)
        return 1

    logger.info("fetching Gaia + AllWISE + 2MASS join for %d candidates", len(source_ids))
    result = sources.fetch_targets_by_source_id(
        source_ids, cache_path=None, use_cache=False
    )
    if result.n_sources == 0:
        logger.error(
            "Gaia returned 0 rows for the registered candidates; check IDs and table names"
        )
        return 2

    merged = result.sources.merge(overrides, on="gaia_dr3_source_id", how="left")
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output, index=False)
    logger.info("Hephaistos join cache ready: %d rows -> %s", len(merged), output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pharos", description="Pharos v0.1 data fetches.")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    qn = subparsers.add_parser(
        "fetch_quiet_negative", help="Fetch the quiet-negative control population from Gaia."
    )
    qn.add_argument("--output", required=True, help="Path to write the parquet cache.")
    qn.add_argument(
        "--limit",
        type=int,
        default=5_000,
        help=(
            "Maximum rows to fetch (default 5000 — sufficient for the v0.1 "
            "stratification, which needs ~30 controls per bin across ~100 bins. "
            "Raise to 50000+ for v1.0 production releases."
        ),
    )
    qn.add_argument(
        "--force-refresh", action="store_true", help="Ignore any existing cache."
    )
    qn.set_defaults(func=cmd_fetch_quiet_negative)

    hef = subparsers.add_parser(
        "fetch_hephaistos",
        help="Fetch Gaia + AllWISE + 2MASS for the Hephaistos candidate set.",
    )
    hef.add_argument(
        "--registry",
        default="controls/hephaistos.yaml",
        help="Path to hephaistos.yaml.",
    )
    hef.add_argument("--output", required=True, help="Path to write the parquet cache.")
    hef.set_defaults(func=cmd_fetch_hephaistos)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

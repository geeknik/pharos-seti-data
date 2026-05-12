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

from pharos import calibration, contaminants, fdr_report, injection, ir_sed, sources, xray

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


def cmd_run_injection_recovery(args: argparse.Namespace) -> int:
    controls_path = Path(args.controls).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not controls_path.exists():
        logger.error("controls cache not found: %s", controls_path)
        return 1

    controls = pd.read_parquet(controls_path)
    controls = ir_sed.add_stratification_bins(ir_sed.add_color_indices(controls))

    result = injection.run_injection_recovery(
        controls,
        sigmas=tuple(float(s) for s in args.sigmas),
        threshold=args.threshold,
        max_pool_size=args.max_pool_size,
        random_state=args.seed,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "injection_rows.parquet"
    summary_path = output_dir / "injection_summary.csv"
    result.rows.to_parquet(rows_path, index=False)
    result.summary.to_csv(summary_path, index=False)
    logger.info(
        "injection recovery saved: rows=%s summary=%s "
        "(locus_size=%d, pool_size=%d)",
        rows_path,
        summary_path,
        result.locus_size,
        result.injection_pool_size,
    )
    print(result.summary.to_string(index=False))
    return 0


def cmd_run_calibration(args: argparse.Namespace) -> int:
    contaminants_path = Path(args.contaminants).resolve()
    controls_path = Path(args.controls).resolve()
    output_path = Path(args.output).resolve()
    pre_reg_path = Path(args.pre_registration).resolve()

    for path, label in [
        (contaminants_path, "contaminants"),
        (controls_path, "controls"),
        (pre_reg_path, "pre_registration"),
    ]:
        if not path.exists():
            logger.error("missing %s fixture: %s", label, path)
            return 1

    contam_df = pd.read_parquet(contaminants_path)
    controls_df = pd.read_parquet(controls_path)

    # Sources that survive the X-ray cross-match are augmented with the
    # xray_any_detection / xray_coverage_count columns. When the
    # cross-match cache exists, we left-join it onto both populations so
    # the v0.1.1 HOT DOG component sees the X-ray data during the fit.
    xray_dir = Path(args.xray_dir).resolve() if args.xray_dir else None
    if xray_dir and xray_dir.exists():
        xray_summary = xray.load_xray_crossmatch(xray_dir).summary
        contam_df = contam_df.merge(xray_summary, on="gaia_dr3_source_id", how="left")
        controls_df = controls_df.merge(xray_summary, on="gaia_dr3_source_id", how="left")
        logger.info("merged X-ray summary onto contaminants and controls")

    result = calibration.calibrate_betas(
        contam_df, controls_df, random_state=args.seed
    )
    calibration.write_calibration_yaml(
        result,
        output_path=output_path,
        contaminants_path=contaminants_path,
        controls_path=controls_path,
        pre_reg_path=pre_reg_path,
    )
    print(f"Calibrated β (train_loss={result.train_loss:.4f}, accuracy={result.train_accuracy:.3f}):")
    for name, val in result.betas.items():
        marker = "" if val > 0 else "  [clipped to 0]"
        print(f"  {name:18s} {val:7.3f}{marker}")
    return 0


def cmd_fetch_contaminants(args: argparse.Namespace) -> int:
    import yaml as _yaml

    output_dir = Path(args.output_dir).resolve()
    result = contaminants.fetch_contaminants_positive(
        hephaistos_yaml=Path(args.hephaistos_yaml).resolve(),
        hephaistos_join_cache=Path(args.hephaistos_join).resolve(),
        quiet_negative_cache=Path(args.quiet_negative).resolve(),
        output_dir=output_dir,
        skip_million_quasars=args.skip_million_quasars,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    result.sources.to_parquet(output_dir / "contaminants.parquet", index=False)
    with open(output_dir / "manifest.yaml", "w", encoding="utf-8") as f:
        _yaml.safe_dump(result.manifest, f, sort_keys=False)
    logger.info(
        "contaminants saved: %s (n=%d)",
        output_dir / "contaminants.parquet",
        len(result.sources),
    )
    return 0


def cmd_fetch_xray(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not input_path.exists():
        logger.error("input cache not found: %s", input_path)
        return 1

    df = pd.read_parquet(input_path)
    # Pull only the columns the X-ray cross-match needs.
    required = ["gaia_dr3_source_id", "ra", "dec", "galactic_l"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.error("input dataframe missing columns: %s", missing)
        return 2
    positions = df[required].copy()

    catalogs = tuple(args.catalogs) if args.catalogs else tuple(xray.XRAY_CATALOGS.keys())
    result = xray.fetch_xray_crossmatch(positions, catalogs=catalogs)
    xray.save_xray_crossmatch(result, output_dir)
    logger.info(
        "X-ray cross-match saved: %s (sources=%d, with_detection=%d)",
        output_dir,
        len(result.summary),
        int(result.summary["xray_any_detection"].sum()),
    )
    return 0


def cmd_run_fdr_report(args: argparse.Namespace) -> int:
    controls_path = Path(args.controls).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not controls_path.exists():
        logger.error("controls cache not found: %s", controls_path)
        return 1

    controls = pd.read_parquet(controls_path)
    controls = ir_sed.add_stratification_bins(ir_sed.add_color_indices(controls))

    result = fdr_report.run_fdr_report(
        controls,
        q_thresholds=tuple(float(q) for q in args.q_thresholds),
        random_state=args.seed,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "fdr_rows.parquet"
    summary_path = output_dir / "fdr_summary.csv"
    result.rows.to_parquet(rows_path, index=False)
    result.summary.to_csv(summary_path, index=False)
    logger.info(
        "FDR report saved: rows=%s summary=%s "
        "(locus=%d, target=%d, null=%d)",
        rows_path,
        summary_path,
        result.locus_size,
        result.target_size,
        result.null_size,
    )
    print(result.summary.to_string(index=False))
    return 0


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

    inj = subparsers.add_parser(
        "run_injection_recovery",
        help="Run the v0.1 synthetic-injection recovery test.",
    )
    inj.add_argument(
        "--controls",
        default="controls/cache/quiet_negative.parquet",
        help="Path to the cached quiet-negative population.",
    )
    inj.add_argument(
        "--output-dir",
        default="controls/synthetic_injection",
        help="Directory to write injection_rows.parquet + injection_summary.csv.",
    )
    inj.add_argument(
        "--sigmas",
        nargs="+",
        default=["5", "10", "20"],
        help="σ levels to inject (default 5 10 20).",
    )
    inj.add_argument(
        "--threshold",
        type=float,
        default=injection.DEFAULT_RECOVERY_THRESHOLD,
        help="ir_evidence threshold counting as 'recovered'.",
    )
    inj.add_argument("--max-pool-size", type=int, default=200)
    inj.add_argument("--seed", type=int, default=0)
    inj.set_defaults(func=cmd_run_injection_recovery)

    fdr = subparsers.add_parser(
        "run_fdr_report",
        help="Run BH FDR calibration on a held-out null sample.",
    )
    fdr.add_argument(
        "--controls",
        default="controls/cache/quiet_negative.parquet",
        help="Path to the cached quiet-negative population.",
    )
    fdr.add_argument(
        "--output-dir",
        default="controls/fdr_report",
        help="Directory to write fdr_rows.parquet + fdr_summary.csv.",
    )
    fdr.add_argument(
        "--q-thresholds",
        nargs="+",
        default=["0.01", "0.05", "0.10"],
        help="q-value cutoffs to report rejection counts at.",
    )
    fdr.add_argument("--seed", type=int, default=0)
    fdr.set_defaults(func=cmd_run_fdr_report)

    xr = subparsers.add_parser(
        "fetch_xray",
        help="X-ray cross-match input positions against 2RXS/XMM/eROSITA/Chandra.",
    )
    xr.add_argument(
        "--input",
        required=True,
        help="Parquet with columns gaia_dr3_source_id, ra, dec, galactic_l.",
    )
    xr.add_argument(
        "--output-dir",
        default="controls/cache/xray",
        help="Directory for xray_summary.parquet and xray_matches.parquet.",
    )
    xr.add_argument(
        "--catalogs",
        nargs="+",
        choices=list(xray.XRAY_CATALOGS.keys()),
        help="Subset of catalogs to query (default: all four).",
    )
    xr.set_defaults(func=cmd_fetch_xray)

    con = subparsers.add_parser(
        "fetch_contaminants",
        help="Build the v0.1.1 contaminant_positive control set.",
    )
    con.add_argument("--hephaistos-yaml", default="controls/hephaistos.yaml")
    con.add_argument("--hephaistos-join", default="controls/cache/hephaistos_join.parquet")
    con.add_argument("--quiet-negative", default="controls/cache/quiet_negative.parquet")
    con.add_argument("--output-dir", default="controls/contaminant_positive")
    con.add_argument(
        "--skip-million-quasars",
        action="store_true",
        help="Skip the Million Quasars fetch (rarely yields any v0.1-coverage sources).",
    )
    con.set_defaults(func=cmd_fetch_contaminants)

    cal = subparsers.add_parser(
        "run_calibration",
        help="Fit non-negative L2 logistic regression β on contaminants vs quiet-negative.",
    )
    cal.add_argument(
        "--contaminants",
        default="controls/contaminant_positive/contaminants.parquet",
        help="Path to the contaminant_positive parquet.",
    )
    cal.add_argument(
        "--controls",
        default="controls/cache/quiet_negative.parquet",
        help="Path to the quiet-negative parquet.",
    )
    cal.add_argument(
        "--xray-dir",
        default="controls/cache/xray",
        help="Directory with xray_summary.parquet (omit to skip X-ray merge).",
    )
    cal.add_argument(
        "--output",
        default="controls/calibrated_betas_v0.1.1.yaml",
        help="Where to write the calibration artifact.",
    )
    cal.add_argument(
        "--pre-registration",
        default="pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md",
        help="Path to the frozen v0.1.1 pre-reg (for provenance hash).",
    )
    cal.add_argument("--seed", type=int, default=calibration.RANDOM_STATE)
    cal.set_defaults(func=cmd_run_calibration)

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

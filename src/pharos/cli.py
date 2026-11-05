"""Command-line entry points for Pharos data and benchmark workflows.

The frozen v0.1.4 workflow exposes separate local preflight, acquisition-role
gate, candidate-review, and registered-release loading commands.  The reviewer
trust root is intentionally empty, so every acquisition and scientific load
fails closed until a prospective authorized workflow establishes it.  The only
v0.1.2 acquisition path is an explicitly named failed-pilot reproduction that
writes a failed/non-authorizing manifest to fixed ignored quarantine paths.

The historical target-fetch command is:

    python -m pharos.cli fetch_hephaistos \\
        --registry controls/hephaistos.yaml \\
        --output controls/cache/hephaistos_join.parquet

Both workflows submit registered ADQL to the Gaia archive (gea.esac.esa.int).
The ``fetch_hephaistos`` command also
merges in W1↔W3 photocentre offsets and other per-candidate fields from
``controls/hephaistos.yaml`` (Suazo et al. 2024 Table 5 / Table 7), so
the resulting parquet has the source columns used by the v0.1 pilot.
Other subcommands reproduce benchmark, injection, and failed v0.1.1
diagnostic workflows; they are labeled accordingly in CLI help.
"""

from __future__ import annotations

import argparse
import logging
import shlex
import sys
from pathlib import Path

import pandas as pd
import yaml

from pharos import (
    artifacts,
    calibration,
    contaminants,
    control_population,
    control_loaders_v014,
    control_workflow_v014,
    fdr_report,
    injection,
    ir_sed,
    sources,
    xray,
)

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


def cmd_fetch_quiet_negative(args: argparse.Namespace) -> int:
    """Historical raw fetch helper; deliberately not authorized by the parser."""
    output = Path(args.output).resolve()
    logger.warning(
        "fetch_quiet_negative produces a raw candidate pool; the registered "
        "BP/RP and external-catalog exclusions must run before calibration"
    )
    result = sources.fetch_quiet_negative_controls(
        cache_path=output, limit=args.limit, use_cache=not args.force_refresh
    )
    logger.info(
        "quiet-negative cache ready: %d rows (query hash %s)",
        result.n_sources,
        result.query_hash[:12],
    )
    return 0


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING - 10 * verbosity
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_repository_relative_path(value: str, *, label: str) -> tuple[Path, str]:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must be a repository-relative path without '..'")
    repository_root = Path(__file__).resolve().parents[2]
    candidate = repository_root / relative
    current = repository_root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ValueError(f"{label} path contains a symlink")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(repository_root):
        raise ValueError(f"{label} resolves outside the repository")
    return resolved, relative.as_posix()


def _v014_publication_parent(value: str) -> Path:
    parent, _ = _resolve_repository_relative_path(value, label="publication_parent")
    return parent


def cmd_v014_control_preflight(args: argparse.Namespace) -> int:
    """Run the frozen local checks without creating an attempt or using a network."""
    try:
        parent = _v014_publication_parent(args.publication_parent)
        result = control_workflow_v014.preflight(publication_parent=parent)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("v0.1.4 local preflight rejected: %s", type(exc).__name__)
        return 2
    if not result.passed:
        print("status: blocked")
        for blocker in result.blockers:
            print(f"blocker: {blocker}")
        return 2
    print("status: passed")
    return 0


def cmd_v014_control_acquire(args: argparse.Namespace) -> int:
    """Gate the dedicated Gaia acquisition role; never open a socket here."""
    try:
        parent = _v014_publication_parent(args.publication_parent)
        control_workflow_v014.require_acquisition_preflight(publication_parent=parent)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("v0.1.4 acquisition role blocked: %s", type(exc).__name__)
        return 2
    logger.error("v0.1.4 acquisition role has no in-process network transport")
    return 2


def cmd_v014_review_candidate(args: argparse.Namespace) -> int:
    """Load one unregistered candidate under the identical clean producer tree."""
    try:
        candidate, _ = _resolve_repository_relative_path(args.candidate_dir, label="candidate_dir")
        loaded = control_loaders_v014.load_candidate_for_review(candidate)
    except (OSError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("v0.1.4 candidate review rejected: %s", type(exc).__name__)
        return 2
    print("status: review_only")
    print(f"manifest_sha256: {loaded.manifest_sha256}")
    print("trusted: false")
    return 0


def cmd_v014_load_registered_raw(args: argparse.Namespace) -> int:
    """Load one exact registered raw checkpoint for the release worker."""
    try:
        repository = Path(__file__).resolve().parents[2]
        loaded = control_loaders_v014.load_registered_raw_checkpoint(args.entry_id, repository)
    except (OSError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("v0.1.4 registered raw checkpoint rejected: %s", type(exc).__name__)
        return 2
    print("status: authorized")
    print(f"registry_entry_id: {loaded.registry_entry_id}")
    print(f"manifest_sha256: {loaded.manifest_sha256}")
    return 0


def cmd_v014_load_registered_final(args: argparse.Namespace) -> int:
    """Run the exact-registry scientific loader with no review-mode fallback."""
    try:
        repository = Path(__file__).resolve().parents[2]
        loaded = control_loaders_v014.load_registered_final_release(args.entry_id, repository)
    except (OSError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("v0.1.4 registered final release rejected: %s", type(exc).__name__)
        return 2
    print("status: authorized")
    print(f"registry_entry_id: {loaded.registry_entry_id}")
    print(f"manifest_sha256: {loaded.manifest_sha256}")
    return 0


def cmd_reproduce_failed_v012_pilot(args: argparse.Namespace) -> int:
    """Reproduce the failed pilot in its fixed ignored quarantine paths."""
    output_arg = control_population.FAILED_V012_OUTPUT_RELATIVE.as_posix()
    raw_cache_arg = control_population.FAILED_V012_RAW_CACHE_RELATIVE.as_posix()
    output_dir, _ = _resolve_repository_relative_path(output_arg, label="output_dir")
    raw_cache, _ = _resolve_repository_relative_path(raw_cache_arg, label="raw_cache")
    command_parts = [
        "python",
        "-m",
        "pharos.cli",
        "reproduce_failed_v012_pilot",
        "--minimum-joined",
        str(args.minimum_joined),
    ]
    if args.force_refresh:
        command_parts.append("--force-refresh")
    generating_command = shlex.join(command_parts)
    result = control_population.reproduce_failed_v012_pilot(
        output_dir=output_dir,
        raw_cache_path=raw_cache,
        minimum_joined_rows=args.minimum_joined,
        generating_command=generating_command,
        use_raw_cache=not args.force_refresh,
    )
    logger.info(
        "failed v0.1.2 pilot reproduced in quarantine: rows=%d exclusions=%d manifest=%s",
        len(result.controls),
        len(result.exclusions),
        result.manifest_path,
    )
    print(f"quarantined rows: {len(result.controls)}")
    print("status: failed")
    print("authorization: non_authorizing")
    print(f"manifest: {result.manifest_path.relative_to(Path(__file__).resolve().parents[2])}")
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
    controls_manifest_path = Path(args.controls_manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not controls_manifest_path.exists():
        logger.error("controls manifest not found: %s", controls_manifest_path)
        return 1
    try:
        release = artifacts.load_authorized_control_release(
            controls_manifest_path,
            release_id=args.controls_release_id,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.error("refusing nonconformant controls: %s", exc)
        return 2
    controls = ir_sed.add_stratification_bins(ir_sed.add_color_indices(release.controls))

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
        "injection recovery saved: rows=%s summary=%s (locus_size=%d, pool_size=%d)",
        rows_path,
        summary_path,
        result.locus_size,
        result.injection_pool_size,
    )
    print(result.summary.to_string(index=False))
    return 0


def cmd_run_calibration(args: argparse.Namespace) -> int:
    contaminants_path = Path(args.contaminants).resolve()
    controls_manifest_path = Path(args.controls_manifest).resolve()
    output_path = Path(args.output).resolve()
    pre_reg_path = Path(args.pre_registration).resolve()

    for path, label in [
        (contaminants_path, "contaminants"),
        (controls_manifest_path, "controls_manifest"),
        (pre_reg_path, "pre_registration"),
    ]:
        if not path.exists():
            logger.error("missing %s fixture: %s", label, path)
            return 1

    try:
        release = artifacts.load_authorized_control_release(
            controls_manifest_path,
            release_id=args.controls_release_id,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.error("refusing nonconformant controls: %s", exc)
        return 2
    contam_df = pd.read_parquet(contaminants_path)
    controls_df = release.controls
    controls_path = release.controls_path

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

    result = calibration.calibrate_betas(contam_df, controls_df, random_state=args.seed)
    calibration.write_calibration_yaml(
        result,
        output_path=output_path,
        contaminants_path=contaminants_path,
        controls_path=controls_path,
        controls_sha256=release.controls_sha256,
        pre_reg_path=pre_reg_path,
    )
    print(
        f"Calibrated β (train_loss={result.train_loss:.4f}, accuracy={result.train_accuracy:.3f}):"
    )
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
    controls_manifest_path = Path(args.controls_manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not controls_manifest_path.exists():
        logger.error("controls manifest not found: %s", controls_manifest_path)
        return 1
    try:
        release = artifacts.load_authorized_control_release(
            controls_manifest_path,
            release_id=args.controls_release_id,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.error("refusing nonconformant controls: %s", exc)
        return 2
    controls = ir_sed.add_stratification_bins(ir_sed.add_color_indices(release.controls))

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
        "FDR report saved: rows=%s summary=%s (locus=%d, target=%d, null=%d)",
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
    result = sources.fetch_targets_by_source_id(source_ids, cache_path=None, use_cache=False)
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
    parser = argparse.ArgumentParser(
        prog="pharos",
        description="Pharos versioned control workflows and historical benchmark tools.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    v014_preflight = subparsers.add_parser(
        "v014_control_preflight",
        help="Run frozen v0.1.4 local checks without an attempt or network access.",
    )
    v014_preflight.add_argument(
        "--publication-parent",
        default="controls/checkpoints/quiet_negative_v0.1.4",
        help="Existing repository-relative parent for a future Gaia candidate.",
    )
    v014_preflight.set_defaults(func=cmd_v014_control_preflight)

    v014_acquire = subparsers.add_parser(
        "v014_control_acquire",
        help=(
            "Enter the fail-closed Gaia acquisition role gate; the catalog network is "
            "available only to the dedicated isolated worker."
        ),
    )
    v014_acquire.add_argument(
        "--publication-parent",
        default="controls/checkpoints/quiet_negative_v0.1.4",
        help="Existing repository-relative parent for the Gaia candidate.",
    )
    v014_acquire.set_defaults(func=cmd_v014_control_acquire)

    v014_review = subparsers.add_parser(
        "v014_review_candidate",
        help="Load an unregistered v0.1.4 candidate in review-only mode.",
    )
    v014_review.add_argument(
        "--candidate-dir",
        required=True,
        help="Repository-relative candidate directory; symlinks are rejected.",
    )
    v014_review.set_defaults(func=cmd_v014_review_candidate)

    v014_raw = subparsers.add_parser(
        "v014_load_registered_raw",
        help="Verify and load one exact trusted v0.1.4 raw-checkpoint registry entry.",
    )
    v014_raw.add_argument("--entry-id", required=True, help="Exact immutable registry ID.")
    v014_raw.set_defaults(func=cmd_v014_load_registered_raw)

    v014_final = subparsers.add_parser(
        "v014_load_registered_final",
        help="Verify and load one exact trusted v0.1.4 final-release registry entry.",
    )
    v014_final.add_argument("--entry-id", required=True, help="Exact immutable registry ID.")
    v014_final.set_defaults(func=cmd_v014_load_registered_final)

    qn_v012 = subparsers.add_parser(
        "reproduce_failed_v012_pilot",
        help=(
            "Reproduce the failed v0.1.2 pilot in fixed ignored quarantine paths; "
            "the output is non-authorizing and cannot enter analysis."
        ),
    )
    qn_v012.add_argument(
        "--minimum-joined",
        type=int,
        default=55_000,
        help="Minimum joined rows before BP/RP and external exclusions (default 55000).",
    )
    qn_v012.add_argument("--force-refresh", action="store_true")
    qn_v012.set_defaults(func=cmd_reproduce_failed_v012_pilot)

    inj = subparsers.add_parser(
        "run_injection_recovery",
        help="Run the v0.1 synthetic-injection recovery test.",
    )
    inj.add_argument(
        "--controls-manifest",
        required=True,
        help="Path to the manifest named by the authorized release registry entry.",
    )
    inj.add_argument(
        "--controls-release-id",
        required=True,
        help="Explicit release identity from the immutable authorization registry.",
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
        "--controls-manifest",
        required=True,
        help="Path to the manifest named by the authorized release registry entry.",
    )
    fdr.add_argument(
        "--controls-release-id",
        required=True,
        help="Explicit release identity from the immutable authorization registry.",
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
        help=(
            "Reproduce experimental v0.1.1 X-ray match diagnostics; output is "
            "not valid for null/coverage scoring."
        ),
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
        help="Reproduce the failed v0.1.1 contaminant-positive control set.",
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
        help="Reproduce the failed v0.1.1 global β calibration; never activates it.",
    )
    cal.add_argument(
        "--contaminants",
        default="controls/contaminant_positive/contaminants.parquet",
        help="Path to the contaminant_positive parquet.",
    )
    cal.add_argument(
        "--controls-manifest",
        required=True,
        help="Path to the manifest named by the authorized release registry entry.",
    )
    cal.add_argument(
        "--controls-release-id",
        required=True,
        help="Explicit release identity from the immutable authorization registry.",
    )
    cal.add_argument(
        "--xray-dir",
        default="controls/cache/xray",
        help="Directory with xray_summary.parquet (omit to skip X-ray merge).",
    )
    cal.add_argument(
        "--output",
        default="pre_registration/failed_attempts/v0.1.1_reproduction_betas.yaml",
        help="Where to write the non-active historical calibration artifact.",
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

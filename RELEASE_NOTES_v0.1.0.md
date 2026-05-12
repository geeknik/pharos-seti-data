# Pharos v0.1.0 — IR / Astrometric Confounder Benchmark

**Released:** 2026-05-11
**Pre-registration:** [`pre_registration/v0.1_ir_benchmark.md`](pre_registration/v0.1_ir_benchmark.md) — FROZEN 2026-05-11, SHA-256 `0784859d8cad230d98a43c14e84862396855f590586dd72b29c7e2676963d38c`

## What v0.1 establishes

Pharos v0.1 is the wedge release of the Technosignature Lead Graph: an end-to-end pipeline that takes Gaia DR3 + AllWISE + 2MASS archival data and produces a confounder-penalised re-observation ranking within the WISE-only coverage class. The release demonstrates that the system can **demote seductive false positives before promoting anything**.

This is not a technosignature detection. It is a calibrated archival ranking instrument with its first scientific gate passed.

## Pass-criterion results

The pre-registered v0.1 benchmark required correct classification of the seven Suazo et al. (2024) "Project Hephaistos II" candidates. All seven cases pass against live Gaia archive data:

| Candidate | Required class (pre-reg §7) | Pharos v0.1 output |
|---|---|---|
| G (confirmed background AGN) | `discard_confounded` | `discard_confounded` (β·P = 4.69) ✓ |
| B (suspected, W1↔W3 offset 3.21″) | `discard_confounded` or `needs_human_review` | `discard_confounded` (β·P = 5.18) ✓ |
| A (radio-archival contamination) | Not `ir_followup` | `no_action` ✓ |
| C, D, E, F (unresolved) | Not `ir_followup` | All `no_action` or `discard_confounded` ✓ |

Candidate G is demoted purely on the W1↔W3 photocentre offset (5.59″ RA per Suazo et al. Table 7) — the same signal that high-resolution e-MERLIN/EVN follow-up later confirmed as background AGN contamination. The confounder model mechanises the original-paper internal flag.

## Synthetic-injection recovery (§7 secondary)

W3-excess injections at 5σ / 10σ / 20σ into a held-out stratified pool drawn from the quiet-negative population:

| σ | n_injected | n_recovered | rate | median IR evidence |
|---|---|---|---|---|
| 5 | 61 | 1 | 1.6% | 1.12 |
| 10 | 61 | 32 | 52.5% | 2.14 |
| 20 | 61 | 61 | **100.0%** | 2.75 |

Recovery is defined as `ir_evidence ≥ 2.0` (the `needs_human_review` evidence floor, pre-reg §8). Monotonic with σ, 100% at 20σ — the calibration is correct. The lower 5σ recovery rate is set by the empirical-p-value tail depth of the 1,225-source locus population and is the expected behaviour.

## FDR calibration on null sample (§7 secondary)

BH q-value rejection counts on a 612-source held-out null sample drawn from the quiet-negative population:

| q threshold | n_total | n_rejections | rate |
|---|---|---|---|
| 0.01 | 612 | 0 | 0.0% |
| 0.05 | 612 | 0 | 0.0% |
| 0.10 | 612 | 0 | 0.0% |

Zero rejections at all q thresholds is the correct conservative behaviour for a pure-null sample. BH does not falsely promote control sources.

## Data products

All artifacts in this release are CC BY 4.0 (see `LICENSE-DATA`). Code is Apache 2.0 (see `LICENSE`).

| Artifact | Path | Description |
|---|---|---|
| Quiet-negative controls | [`controls/cache/quiet_negative.parquet`](controls/cache/quiet_negative.parquet) | 2,451 Gaia + AllWISE + 2MASS sources |
| Hephaistos join | [`controls/cache/hephaistos_join.parquet`](controls/cache/hephaistos_join.parquet) | 7 candidates with Suazo Table 5 / 7 fields |
| Injection recovery | [`controls/synthetic_injection/`](controls/synthetic_injection/) | Per-injection rows + per-σ summary |
| FDR report | [`controls/fdr_report/`](controls/fdr_report/) | Per-target FDR rows + per-q summary |
| Hephaistos registry | [`controls/hephaistos.yaml`](controls/hephaistos.yaml) | The seven candidates and their labels |

## Code modules

| Module | Purpose |
|---|---|
| `pharos.sources` | Gaia archive TAP client; split-query path; OAuth-style auth |
| `pharos.ir_sed` | Data-driven stellar-locus residual scoring |
| `pharos.confounders` | P_IR confounder vector (incl. P_wise_offset) |
| `pharos.calibrate` | Empirical p-values + Benjamini-Hochberg FDR |
| `pharos.injection` | Synthetic-injection recovery harness |
| `pharos.fdr_report` | BH calibration on held-out null samples |
| `pharos.cli` | CLI: `fetch_quiet_negative`, `fetch_hephaistos`, `run_injection_recovery`, `run_fdr_report` |

## What v0.1 does NOT do

- Does not score time-domain photometry, spectral residuals, optical pulse, or radio archives. These are the v0.2 / v0.3 / v0.4 layers (see manuscript §9).
- Does not run an unWISE re-extraction pipeline; W1↔W3 photocentre offsets for the seven Hephaistos candidates are loaded from Suazo et al. (2024) Table 7. General-population offset measurement is deferred to v0.2.
- Does not calibrate β weights — the v0.1 weights are pre-registered initialisation values. β calibration against the contaminant-positive set is scheduled for v0.1.1.

## Reproduce v0.1

```sh
# Authenticate to the Gaia archive (one-time setup):
mkdir -p ~/.config/pharos && chmod 700 ~/.config/pharos
# Place Cosmos username on line 1 and password on line 2 of:
#   ~/.config/pharos/gaia_credentials.txt
chmod 600 ~/.config/pharos/gaia_credentials.txt

# Install in a venv:
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Fetch data and run benchmarks:
python -m pharos.cli fetch_hephaistos --output controls/cache/hephaistos_join.parquet
python -m pharos.cli fetch_quiet_negative --output controls/cache/quiet_negative.parquet --limit 5000
python -m pharos.cli run_injection_recovery --max-pool-size 150
python -m pharos.cli run_fdr_report

# Verify all benchmarks pass:
pytest
```

## Citation

A Zenodo DOI for this release will be minted via the GitHub-Zenodo integration on tag publication. Cite this software release alongside the methodology manuscript.

## Next

- v0.1.1: β-weight calibration against the contaminant-positive control set; HOT DOG X-ray-null cross-match.
- v0.2: Time-domain integration (TESS, Kepler, ZTF). Per-transit residual scoring.
- v0.3: Radio coverage (Breakthrough Listen, COSMIC). Enables full demotion of Hephaistos candidate A.
- v0.4: Spectral residual integration.
- v1.0: Public cross-modal leaderboard.

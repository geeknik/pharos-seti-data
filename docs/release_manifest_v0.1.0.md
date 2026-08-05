# Pharos v0.1.0 Release Payload and Conformance Record

**Audit date:** 2026-08-05

**Git tag:** `v0.1.0`

**Tag commit:** `57a2278be459ecf8bc4e2590dc11edc3cf33cc38`

**Zenodo record:** [`10.5281/zenodo.20130607`](https://doi.org/10.5281/zenodo.20130607)

**Zenodo publication date:** 2026-05-12

This document records what the immutable v0.1.0 release actually contains and separates executed benchmark results from unfulfilled frozen requirements. It does not modify the archived release.

## Archive Identity

| Field | Value |
|---|---|
| Zenodo file | `geeknik/pharos-seti-data-v0.1.0.zip` |
| Size | 634,743 bytes |
| Zenodo MD5 | `964e335177080aef88baeb924d90dfab` |
| Independently computed SHA-256 | `1154285e9c37555708ff9da9ad764de95c63d50297612e34b27adec855b20808` |
| Archive form | GitHub-generated source snapshot at the v0.1.0 tag |

The Zenodo API exposed one file at audit time: the archive above.

## Included Benchmark/Data Artifacts

| Artifact | Archived path | Rows / role |
|---|---|---|
| Quiet-negative cache | `controls/cache/quiet_negative.parquet` | 2,451 sources |
| Quiet-negative query sidecar | `controls/cache/quiet_negative.parquet.meta` | Query text/provenance |
| Hephaistos join | `controls/cache/hephaistos_join.parquet` | Seven benchmark candidates |
| Injection rows | `controls/synthetic_injection/injection_rows.parquet` | Per-injection recovery rows |
| Injection summary | `controls/synthetic_injection/injection_summary.csv` | Recovery by injected sigma |
| Null-FDR rows | `controls/fdr_report/fdr_rows.parquet` | Held-out-null lead p/q values |
| Null-FDR summary | `controls/fdr_report/fdr_summary.csv` | Rejections by q threshold |
| Candidate registry | `controls/hephaistos.yaml` | Labels and source provenance |
| Frozen registration | `pre_registration/v0.1_ir_benchmark.md` | v0.1 rules at tag time |
| Code and tests | `src/pharos/`, `tests/` | v0.1 implementation and local gates |

## Registered Artifacts Not Included

The frozen v0.1 registration listed the following release artifacts, but they are absent from the Zenodo archive:

- `lead_graph_catalog_v0.1.csv`
- `modality_scores.parquet`
- `confounder_vectors.parquet`
- `coverage_masks.parquet`
- `fdr_by_coverage_class.csv` under that registered name
- a reproduction notebook for the Hephaistos pass criterion

The archived `controls/fdr_report/fdr_summary.csv` is a null-calibration report; it is not a substitute for a ranked catalog-wide FDR artifact.

## Frozen-Requirement Conformance

| Requirement | Result | Evidence |
|---|---|---|
| Hephaistos classification gate | Pass | Release notes and archived join/control fixtures |
| Synthetic injection recovery | Pass for reported gate | 100% at 20 sigma; monotonic reported recovery |
| Held-out-null BH report | Pass for reported gate | Zero rejections at q up to 0.10 on 612 targets |
| Quiet-negative population at least 50,000 | **Not met** | Archived cache has 2,451 rows |
| Magnitude-binned BP/RP-excess cut | **Not implemented** | Fetch query selects the field but does not apply the registered cut |
| External YSO/AGN/debris exclusions | **Not implemented** | Fetcher explicitly defers the post-query crossmatch; no filtered artifact is archived |
| Full registered artifact set | **Not met** | Missing files listed above |

## Interpretation Boundary

v0.1.0 is a released **pilot benchmark snapshot**. It supports the narrow statement that the executed seven-candidate classification, injection-recovery, and held-out-null checks produced the reported results on the archived fixtures. It does not support the broader claim that a fully registered WISE-coverage source catalog was released.

Before a later version is described as conformant, release automation must compare an explicit manifest against the staged archive, verify hashes and row counts, check every pre-registered population filter, and fail publication when a required artifact is absent.

## License Metadata Note

The Zenodo record advertises Apache-2.0 at record level, while the archive contains code under Apache-2.0 and data/research outputs under CC BY 4.0. Reusers must follow the file classification in `LICENSE` and `LICENSE-DATA`. A future deposit should make the mixed-license boundary explicit in its record description or separate software and data deposits.

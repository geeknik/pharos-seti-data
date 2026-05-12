# Pharos

[![DOI](https://zenodo.org/badge/1235096610.svg)](https://doi.org/10.5281/zenodo.20130606) [![Latest release](https://img.shields.io/github/v/release/geeknik/pharos-seti-data?include_prereleases&label=release)](https://github.com/geeknik/pharos-seti-data/releases)

**A cross-modal archival SETI ranking framework.**

Pharos is a public, versioned instrument for ranking sky objects by calibrated, independent anomaly evidence across archival astronomical surveys. It is *not* a technosignature detector. It is a re-observation priority catalog: a system that converts archival anomalies into disciplined follow-up targets after known astrophysical and instrumental confounders are scored together.

The methodology is described in [`manuscript.md`](manuscript.md) under the conceptual name *Technosignature Lead Graph*. Pharos is the operational name of the instrument and the public catalog.

This repository contains the methodology, scoring code, control populations, and data outputs. The public landing site lives in a companion repository, [`pharos-seti-web`](https://github.com/geeknik/pharos-seti-web) (private).

## Status

| Version | Scope | State |
|---|---|---|
| v0.1 | IR / Astrometric Confounder Benchmark | In development |
| v0.2 | Time-domain integration (TESS, Kepler, ZTF) | Not started |
| v0.3 | Radio coverage (Breakthrough Listen, COSMIC) | Not started |
| v0.4 | Spectral residual integration (HIRES, HARPS, LAMOST) | Not started |
| v1.0 | Public cross-modal leaderboard | Not started |

v0.1's pass criterion is concrete: the system must demote the three Hephaistos candidates with known or suspected background-source contamination into `discard_confounded` or `needs_human_review`, and must not promote the remaining four into top-tier `ir_followup` without independent inspection. See [`pre_registration/v0.1_ir_benchmark.md`](pre_registration/v0.1_ir_benchmark.md) for the frozen scoring rules.

## Repository Layout

```
manuscript.md                — methodology and architecture
pre_registration/            — frozen scoring rules, fixed before any candidate data is queried
src/pharos/                  — Python package (scoring code)
controls/                    — calibration_positive, contaminant_confirmed,
                               contaminant_suspected, quiet_negative, synthetic_injection
notebooks/                   — reproduction notebooks per release
tests/                       — benchmark harness (Hephaistos demotion test, injection recovery)
docs/                        — model card, release notes
```

## Data Releases

Versioned data releases are published to Zenodo with DOIs. Each release ships the ranked catalog, modality scores, confounder vectors, coverage masks, control populations, and a frozen pre-registration document. Release artifacts are listed in [manuscript.md §8](manuscript.md).

## Citation

Cite both the software release (via the Zenodo DOI for the relevant version) and the methodology manuscript. A `CITATION.cff` file is provided at the repository root for tool-readable metadata.

**v0.1.0 release DOI:** [`10.5281/zenodo.20130607`](https://doi.org/10.5281/zenodo.20130607)

## License

This repository is dual-licensed:

- **Code** (`src/`, `tests/`, `notebooks/` Python source, build configuration) is licensed under the [Apache License 2.0](LICENSE).
- **Data and research outputs** (manuscript, pre-registration documents, model card, control populations, published catalogs and modality scores, and other data artifacts) are licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-DATA).

See [`LICENSE`](LICENSE) and [`LICENSE-DATA`](LICENSE-DATA) for the full terms and the file-classification breakdown.

## Contact

Maintainer contact and project home: [pharos-seti.org](https://pharos-seti.org).

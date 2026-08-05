# Pharos

[![DOI](https://zenodo.org/badge/1235096610.svg)](https://doi.org/10.5281/zenodo.20130606) [![Latest release](https://img.shields.io/github/v/release/geeknik/pharos-seti-data?include_prereleases&label=release)](https://github.com/geeknik/pharos-seti-data/releases)

**A cross-modal archival SETI ranking framework.**

Pharos is a public, versioned instrument for ranking sky objects by calibrated, independent anomaly evidence across archival astronomical surveys. It is *not* a technosignature detector. It is a re-observation priority catalog: a system that converts archival anomalies into disciplined follow-up targets after known astrophysical and instrumental confounders are scored together.

The methodology is described in [`manuscript.md`](manuscript.md) under the conceptual name *Technosignature Lead Graph*. Pharos is the operational name of the instrument and the public catalog.

This repository contains the methodology, scoring code, control populations, and data outputs. The public landing site lives in a companion repository, [`pharos-seti-web`](https://github.com/geeknik/pharos-seti-web) (private).

## Status

| Version | Scope | State |
|---|---|---|
| v0.1.0 | IR / Astrometric Confounder Benchmark | Released pilot; post-release conformance gaps documented |
| v0.1.1 | Global β calibration + X-ray attenuation | Failed registered attempt; did not ship |
| v0.1.2 | Subtype-aware confounders + X-ray evidence | Pre-registration frozen; conformant control builder implemented; model fit pending |
| v0.2 | Time-domain integration (TESS, Kepler, ZTF) | Not started |
| v0.3 | Radio coverage (Breakthrough Listen, COSMIC) | Not started |
| v0.4 | Spectral residual integration (HIRES, HARPS, LAMOST) | Not started |
| v1.0 | Public cross-modal leaderboard | Not started |

v0.1.0 passed its Hephaistos classification, synthetic-injection, and held-out-null FDR checks. A post-release audit also found that it did **not** satisfy every frozen release requirement: the quiet-negative population was smaller than registered, registered exclusions were not fully applied, and several promised derived artifacts were absent. Treat v0.1.0 as a pilot benchmark, not a complete catalog release. See [`docs/release_manifest_v0.1.0.md`](docs/release_manifest_v0.1.0.md) for the exact payload and conformance record.

The failed v0.1.1 attempt is preserved under [`pre_registration/failed_attempts/`](pre_registration/failed_attempts/). Its fitted weights and X-ray attenuation rule are not active. The superseding v0.1.2 rules are frozen in [`pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md`](pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md).

### Build the v0.1.2 quiet-negative fixture

The first v0.1.2 implementation slice builds the registered control population only; it does not fit or activate a model:

```bash
python -m pharos.cli -v build_quiet_negative_v012 \
  --output-dir controls/quiet_negative_v0.1.2 \
  --raw-cache controls/cache/quiet_negative_v0.1.2.raw.parquet \
  --minimum-joined 55000
```

Remote requests are capped at 500 source positions. Responses must match exact schemas and pass coordinate, identifier, numeric-bound, and duplicate checks before use. The builder applies the magnitude-binned BP/RP excess-factor cut and 30-arcsecond SIMBAD YSO/AGN and Chen debris-disk exclusions. Acquisition checkpoints are atomic, hash-validated local working state. A final fixture is published only when at least 50,000 controls survive, and calibration/FDR commands refuse legacy parquet files without the exact v0.1.2 manifest.

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

## Releases

Versioned releases are published to Zenodo with DOIs. The v0.1.0 Zenodo record contains the tagged software snapshot plus benchmark/control artifacts; it does not contain the complete derived catalog artifact set described for v1.0 in [manuscript.md §8](manuscript.md). Every future release must publish and verify an exact payload manifest before it is described as complete.

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

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
| v0.1.2 | Subtype-aware confounders + X-ray evidence | Hardened control pilot failed scientific conformance; artifacts quarantined; did not ship |
| v0.1.3 | Hardened quiet-negative control population | Preregistration frozen; implementation blocked; acquisition prohibited |
| v0.1.4 | Producer-provenance repair of the control protocol | Prospective supersession required; not registered |
| v0.2 | Time-domain integration (TESS, Kepler, ZTF) | Not started |
| v0.3 | Radio coverage (Breakthrough Listen, COSMIC) | Not started |
| v0.4 | Spectral residual integration (HIRES, HARPS, LAMOST) | Not started |
| v1.0 | Public cross-modal leaderboard | Not started |

v0.1.0 passed its Hephaistos classification, synthetic-injection, and held-out-null FDR checks. A post-release audit also found that it did **not** satisfy every frozen release requirement: the quiet-negative population was smaller than registered, registered exclusions were not fully applied, and several promised derived artifacts were absent. Treat v0.1.0 as a pilot benchmark, not a complete catalog release. See [`docs/release_manifest_v0.1.0.md`](docs/release_manifest_v0.1.0.md) for the exact payload and conformance record.

The failed v0.1.1 attempt is preserved under [`pre_registration/failed_attempts/`](pre_registration/failed_attempts/). Its fitted weights and X-ray attenuation rule are not active. The later v0.1.2 hardened control-population pilot also **did not ship**: it used scientifically material population-selection rules that were not prospectively registered. Its data and manifests remain quarantined and must not be used for fitting, calibration, ranking, or release. See the exact [v0.1.2 non-release record](pre_registration/failed_attempts/v0.1.2_hardened_control_population.md).

The prospective replacement is [v0.1.3](pre_registration/v0.1.3_control_population.md). Its reviewed bytes are frozen in [`pre_registration/FROZEN.md`](pre_registration/FROZEN.md) (87,851 bytes, SHA-256 `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`), but the protocol is not executable as frozen: the final artifact schema requires distinct raw-checkpoint and final-release producers while permitting only one embedded source distribution, the authorized-reviewer signing-key trust root is empty, and the locked dependency audit fails. No v0.1.3 catalog query, acquisition, checkpoint, exclusion request, or model operation may run. A prospective v0.1.4 supersession must repair the producer-provenance model and the reviewer trust root before implementation; see [`docs/v0.1.3-experimental-scaffold.md`](docs/v0.1.3-experimental-scaffold.md).

### Control-population execution status

There is currently no authorized control-population build command. The old v0.1.2 command would reproduce a quarantined failed pilot, not a release, and is intentionally not documented as an executable workflow. v0.1.3 is frozen but blocked; implementation and fresh acquisition must wait for a prospective v0.1.4 supersession and then follow its candidate, independent-review, review-evidence-commit, and registry-commit sequence exactly. Pilot rows, cursors, response tables, and allow-list entries are prohibited inputs.

## Repository Layout

```
manuscript.md                — methodology and architecture
pre_registration/            — prospective drafts, frozen rules, and failed-attempt records
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

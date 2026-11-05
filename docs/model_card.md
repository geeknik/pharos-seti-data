# Pharos Model Card

**Version:** 0.1.0
**Status:** Released pilot benchmark. The executed benchmark checks passed, but a post-release audit found frozen-requirement and payload gaps; see [`release_manifest_v0.1.0.md`](release_manifest_v0.1.0.md).

A model card for the Pharos archival anomaly ranking system. This document states what the score means, what it does not mean, what populations it covers, and where it is known to be unreliable. Every public release updates this card.

## What Pharos Is

A versioned public instrument for ranking sky objects by calibrated, independent anomaly evidence across archival astronomical surveys. The output is a re-observation priority catalog with empirical p-values and Benjamini-Hochberg FDR control, stratified by coverage class.

## What Pharos Is Not

- Not a technosignature detector.
- Not a statement that any ranked source is anomalous in an astrophysical sense.
- Not a claim that confounder labels exhaust the set of natural explanations.
- Not a substitute for follow-up observation and human astrophysical judgment.

A high LeadScore means "the archival evidence available to Pharos in this coverage class is unusual in this combination after the system's confounder model has been applied." It does not mean "this source is more likely to host technology." The system controls the re-observation queue; it does not adjudicate physical hypotheses.

## Intended Use

- Generating prioritized lists for follow-up observation programs.
- Stress-testing confounder models against known contamination cases.
- Providing a citeable, reproducible baseline against which alternative ranking systems can be compared.

## Out-of-Scope Use

- Single-source detection claims.
- Population-level inferences about technosignature prevalence.
- Any use that ignores the coverage class stratification.

## Coverage Class (v0.1)

v0.1 scores sources only in the WISE-only coverage class:

- Gaia DR3 source with `parallax_over_error >= 5`, `phot_g_mean_mag <= 18.0`, distance ≤ 200 pc
- AllWISE crossmatch with `angular_distance <= 3.0″`
- W1, W2 detections at S/N ≥ 5; W3 detection at S/N ≥ 3
- 2MASS counterpart within 1.5″

Sources outside this class receive no v0.1 pilot score. Their absence from the published benchmark archive is not a negative result.

## Release Conformance (v0.1.0)

v0.1.0 successfully ran the seven-source Hephaistos classification gate, synthetic W3-excess recovery, and held-out-null FDR report. It is not a fully conformant realization of the frozen v0.1 registration:

- the published quiet-negative cache contains 2,451 rows, below the registered minimum of 50,000;
- the magnitude-binned `phot_bp_rp_excess_factor` cut was not implemented;
- the registered external exclusions for known YSOs, AGN, and debris disks were not applied to the quiet-negative cache;
- the Zenodo archive does not include the registered ranked catalog, modality-score table, confounder-vector table, coverage-mask table, or reproduction notebook.

Consequently, v0.1.0 supports only the bounded benchmark results reported in its release notes. It must not be presented as a complete WISE-coverage ranking catalog.

## Known Limitations (v0.1)

- **β weights are not calibrated.** Pre-registered initialization values are used in v0.1. The v0.1.1 global calibration failed and did not ship. The v0.1.2 hardened control-population pilot, which was to supply the subtype-specific models, failed scientific conformance and is quarantined; nothing from it is fitted or active. The v0.1.3 control-population protocol is frozen but blocked by a producer-provenance schema contradiction, an empty reviewer signing-key trust root, and a failing dependency audit; the v0.1.4 supersession repairing these provisions was frozen 2026-11-05 and its implementation has not started. No control population from any of these protocols exists yet.
- **GSP-Phot distance is not independent of parallax.** Pharos does not use `distance_gspphot_pc` as an independent anomaly feature. External photometric/spectroscopic distances are required for the `distance_discrepancy_noparallax_z` channel.
- **No radio, optical pulse, time-domain, or spectral residual scoring in v0.1.** A high IR evidence score in v0.1 has no cross-modal independence weight applied because no second modality is online.
- **HOT DOG probability is heuristic.** v0.1 uses a simple Gaia-faint + WISE-bright + no-DSC-QSO indicator. The failed v0.1.1 X-ray attenuation rule is inactive; X-ray detection does not rule out an obscured AGN.
- **The empirical stellar locus is shallow.** Its 2,451-source control population limits tail resolution and leaves many registered stratification cells sparse enough to use coarser fallbacks.

## Failure Modes

- **WISE source confusion in dense fields.** The graph penalizes via `angular_distance` and `number_of_neighbours`, but extreme confusion can still leak signal.
- **Background AGN/HOT DOG contamination.** Confirmed in the Hephaistos candidate G case; the v0.1 confounder model is built specifically to demote this pattern, but extreme cases may require independent radio data to suppress.
- **Poor GSP-Phot fits.** GSP-Phot distance is parallax-dependent and is not an independent anomaly channel. v0.1.0 does not publish the registered no-parallax distance-discrepancy product.

## Reporting

If you find a failure mode the model card does not describe, please open an issue. The card is updated each release.

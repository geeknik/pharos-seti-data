# Pharos Model Card

**Version:** 0.1.0-dev
**Status:** v0.1 in development; no scores published yet.

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

Sources outside this class receive no v0.1 score. Their absence from the catalog is not a negative result.

## Known Limitations (v0.1)

- **β weights are not calibrated.** Pre-registered initialization values are used in v0.1. Calibration against the contaminant-positive control set is scheduled for v0.1.1.
- **GSP-Phot distance is not independent of parallax.** Pharos does not use `distance_gspphot_pc` as an independent anomaly feature. External photometric/spectroscopic distances are required for the `distance_discrepancy_noparallax_z` channel.
- **No radio, optical pulse, time-domain, or spectral residual scoring in v0.1.** A high IR evidence score in v0.1 has no cross-modal independence weight applied because no second modality is online.
- **HOT DOG probability is heuristic.** v0.1 uses a simple Gaia-faint + WISE-bright + no-DSC-QSO indicator; a calibrated HOT DOG classifier is a v0.2+ task.
- **Stellar SED grid is fixed at freeze time.** Sources whose true atmospheric parameters fall outside the grid coverage may have unreliable photospheric predictions.

## Failure Modes

- **WISE source confusion in dense fields.** The graph penalizes via `angular_distance` and `number_of_neighbours`, but extreme confusion can still leak signal.
- **Background AGN/HOT DOG contamination.** Confirmed in the Hephaistos candidate G case; the v0.1 confounder model is built specifically to demote this pattern, but extreme cases may require independent radio data to suppress.
- **Poor GSP-Phot fits.** Sources with `distance_gspphot_pc` strongly inconsistent with `distance_parallax_pc` are flagged via `D` (data quality penalty), but a source with a poor GSP-Phot fit and a real IR excess will be conservatively demoted.

## Reporting

If you find a failure mode the model card does not describe, please open an issue. The card is updated each release.

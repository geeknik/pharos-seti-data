# The Technosignature Lead Graph: A Cross-Modal Ranking Framework for Archival SETI

## Abstract
We propose the Technosignature Lead Graph, a cross-modal archival SETI framework that ranks public sky objects by calibrated, independent anomaly evidence rather than by single-channel signal hypotheses. Gaia DR3 serves as the source spine, with modality layers from WISE/AllWISE infrared photometry, three separated optical channels (time-domain photometry, spectral residuals, nanosecond pulse detection), Breakthrough Listen and COSMIC radio archives, planetary-system architecture, and event-geometry priors such as the SETI Ellipsoid and Earth Transit Zone. Each source receives modality-specific empirical tail probabilities, coverage masks, independence-weighted cross-modal bonuses, and penalties for known astrophysical and instrumental confounders including WISE confusion, dust, young stellar objects, AGN, binaries, crowding, and poor astrometric quality. The output is not a technosignature detection claim, but a reproducible re-observation priority catalog: objects whose archival anomaly evidence survives independent measurement, coverage, and confounder controls.

***
## 1. Problem
There is no widely adopted, public, versioned system that integrates technosignature-relevant anomalies across independent archival modalities into a confounder-penalized follow-up ranking catalog.

Existing approaches demonstrate the gap clearly. Single-modality searches dominate the published record: narrowband radio surveys of hundreds of stars, WISE infrared color cuts producing candidate lists before confounder suppression, and machine-learning anomaly catalogs over light curves without a persistent re-observation ranking layer. Each approach is scientifically sound within its domain but structurally insufficient for producing credible follow-up targets, because any single channel's anomaly rate is dominated by astrophysical and instrumental false positives that disappear under independent scrutiny.

The correct architecture is a cross-catalog ranking engine: a system that scores objects across independent modalities, weights by empirically estimated independence, penalizes confounders, tracks data coverage explicitly, applies false-discovery control, and outputs a reproducible re-observation priority list stratified by coverage class. This paper proposes that system.

***
## 2. Principle
Single-channel anomalies are not leads. Cross-modal, confounder-penalized anomalies are leads.

The argument is statistical. WISE mid-IR excess in W3/W4 is dominated by young stellar objects, debris disks, background galaxies, and source confusion from the broad WISE long-wavelength point-spread function. Narrowband radio candidates are dominated by RFI. Anomalous Kepler light curves are dominated by instrumental systematics and binary stars. A source that independently clears elevated thresholds in IR photometry, radio archives, and time-domain photometry — with each channel's confounder model applied separately — has a joint false positive probability orders of magnitude below any single-channel equivalent, assuming genuine independence between channels.

**The graph rewards cross-modal independence, not anomaly count.** Two anomalies sharing the same systematic errors contribute little more than one. Two anomalies from physically orthogonal measurement systems are the product that matters. The graph does not assume independence; it estimates independence from control populations and exposes the independence matrix as a public artifact.

***
## 3. Graph Construction
### 3.1 Gaia DR3 Spine
Gaia DR3 is the correct spine because it delivers source identity, parallax-based distance, astrometric quality flags, low-resolution BP/RP spectra, astrophysical parameter estimates, and external catalog crossmatch infrastructure in a single public release. Relevant fields:

- **Astrometry:** `ra`, `dec`, `parallax`, `parallax_over_error`, `pmra`, `pmdec`, `ruwe`, `astrometric_excess_noise`, `astrometric_excess_noise_sig`
- **Photometry:** `phot_g_mean_mag`, `phot_bp_rp_excess_factor`, `ipd_frac_multi_peak`, `ipd_frac_odd_win`
- **Quality and classification flags:** `duplicated_source`, Non-Single-Star (NSS) table membership, `classprob_dsc_combmod_quasar`, `classprob_dsc_combmod_galaxy`
- **Astrophysical parameters (GSP-Phot):** `teff_gspphot`, `logg_gspphot`, `distance_gspphot`, `ag_gspphot` — derived by Bayesian forward-modelling that simultaneously fits the BP/RP spectrum, parallax, and apparent G magnitude (Andrae et al., Gaia DR3 GSP-Phot)
- **External joins:** Gaia source IDs joined to 2MASS and AllWISE through Gaia archive best-neighbour and neighbourhood crossmatch tables; the `gaiadr3.allwise_best_neighbour` fields `angular_distance`, `xm_flag`, `number_of_neighbours`, and `number_of_mates` are inputs to the confounder model, not metadata to be discarded

**Distance fields — do not collapse.** GSP-Phot simultaneously fits BP/RP spectra, parallax, and apparent G magnitude in a single forward model. Its distance estimate is therefore not independent of parallax. The distance consistency check requires an external, no-parallax photometric or spectroscopic distance:

| Field | Source | Use |
|---|---|---|
| `distance_parallax_pc` | Gaia parallax | Geometric distance |
| `distance_gspphot_pc` | GSP-Phot Bayesian fit | Internal consistency check only |
| `distance_photometric_noparallax_pc` | External spectroscopy / multiband photometry (APOGEE, LAMOST, or isochrone-based) | Genuinely independent distance |
| `distance_discrepancy_noparallax_z` | Derived | Structural anomaly feature |

The discrepancy between `distance_parallax_pc` and `distance_gspphot_pc` is a self-consistency field — useful for flagging poor GSP-Phot fits but not an independent anomaly signal, because both terms share the Gaia parallax measurement. Only `distance_discrepancy_noparallax_z`, built from a source that does not consume Gaia parallax, can enter the cross-modal independence calculation.

The RUWE threshold of 1.4 is the standard DR3 filter for astrometric excess. The Lead Graph applies a sliding `DataQualityPenalty` on `ruwe` and `astrometric_excess_noise_sig` rather than a binary cutoff. Gaia DR3 Non-Single-Star (NSS) solutions serve two roles: confounder detector (a blended system's IR excess is not stellar) and independent anomaly source (an astrometrically-resolved companion near a radio candidate is informative).

### 3.2 WISE / AllWISE Infrared Layer
WISE All-Sky provides photometry for 563,921,584 cataloged sources at 3.4, 4.6, 12, and 22 μm (WISE/IPAC). AllWISE extends the combined cryogenic and post-cryogenic release to over 747 million objects (NASA/IPAC AllWISE release). WISE W3/W4 excess is high-value but high-risk: the long-wavelength point-spread functions are broad, making background galaxies and source confusion first-order contaminants, not secondary quality flags. The IR layer treats angular contamination as a primary penalty, not a secondary flag.

The IR modality score is the SED residual: fit a stellar photosphere model using GSP-Phot `teff_gspphot`, `logg_gspphot`, and `ag_gspphot`, predict W1 through W4 photospheric emission, and compute the calibrated evidence score \(E_{\text{IR}}\) (Section 5.1) from the z-scored W3/W4 excess against matched controls.

**Project Hephaistos as stress test.** Suazo et al. built a Gaia–2MASS–WISE pipeline filtering approximately five million objects, applied a CNN for WISE source confusion, and identified seven M-dwarf candidates with anomalous IR excess. Subsequent high-resolution e-MERLIN and EVN observations of one of these candidates — referred to here as candidate G — resolved the radio emission into compact background components with brightness temperature characteristic of a radio-loud AGN, with no radio emission detected at the M-dwarf's Gaia position (MNRAS Letters). The mid-IR excess previously attributed to candidate G is therefore confirmed contamination by a background AGN.

**Candidate G is a confirmed high-resolution background-source contamination case. Candidates A and B are suspected contamination cases based on radio-source offsets and remain stress-test contaminants pending equivalent high-resolution follow-up.** The remaining four Hephaistos candidates are unresolved and should not be pre-declared contaminants; they are stress-test cases for the confounder model.

This contamination history is the strongest possible argument for the Lead Graph's confounder architecture: any IR-excess candidate whose WISE W3/W4 flux can be plausibly attributed to a nearby background AGN or HOT DOG — flagged by angular offset between an archival radio source and the Gaia stellar position, or by multi-frequency SED morphology inconsistent with stellar photosphere plus single-temperature excess — should be demoted unless an independent modality survives the same scrutiny.

IR layer confounder penalties:
- WISE `cc_flags`, `ext_flg`, `nb` (number of fit components), `w?snr`, `w?sat` flags
- `angular_distance`, `number_of_neighbours`, and `number_of_mates` from `gaiadr3.allwise_best_neighbour`
- `classprob_dsc_combmod_galaxy` and `classprob_dsc_combmod_quasar` from Gaia DSC
- Galactic latitude penalty (|b| < 10°)
- YSO and debris-disk color profile indicators from spectroscopic survey crossmatch
- HOT DOG probability: faint optical / near-IR, bright mid-IR, no X-ray counterpart pattern

### 3.3 Time-Domain Optical Layer
Standard exoplanet photometry phase-folds transits on the assumption that each event is identical. This is precisely the step that erases non-repeating or morphologically variable transit events. Zuckerman et al. applied individual-transit residual detection to 218 confirmed Kepler transiting exoplanet systems, explicitly noting that phase-folding suppresses information about modification of transit signals.

The Lead Graph uses per-planet normal transit models with individual-transit residual scoring. Flags scored per transit: asymmetric ingress/egress ratio, depth change exceeding the photometric noise model, duration change, missing transits at predicted phase, and brightening events at transit phase. Boyajian's Star (KIC 8462852) is the benchmark case demonstrating why per-transit morphology matters as a search axis — not evidence for technology — with aperiodic dimming events driving development of asymmetric-transit detection pipelines.

The ZTF/Lasair alert broker workflow demonstrated in 2025 operationalizes high-amplitude dipper searches, ETZ filtering, and SETI Ellipsoid event timing over approximately one million nightly alerts, reducing to fewer than five candidates per night after full post-processing.

**Coverage note:** No-coverage is not a negative result. Time-domain modality scores are computed only when usable photometric coverage exists; `coverage_mask_tess` and `coverage_mask_ztf` flags are set independently.

### 3.4 Spectral Residual Optical Layer
The Keck HIRES optical laser search examined 2,796 stars — including 1,368 Kepler Objects of Interest — over 3,640–7,890 Å at high spectral resolution and found no laser emission consistent with a technosignature. The search framing was narrow; the stronger approach is stellar-template residual mining: fit the best stellar spectral template, subtract it, remove all known atomic and molecular lines, and search the residuals for non-atomic ultra-narrow emission, repeated line spacing, artificially simple frequency ratios, and Doppler-consistent velocity drift. This is a distinct modality from time-domain photometry and carries its own coverage mask, confounder model, and control set. (Integration scheduled for v0.4; see Section 9.)

### 3.5 Optical Pulse Layer
The VERITAS/Breakthrough Listen optical nanosecond-pulse search analyzed 30 hours of dedicated observations of 136 targets and 249 archival observations of 140 targets dating to 2012. VERITAS used the CALIOP instrument aboard the CALIPSO satellite — a space-based pulsed laser emitting 20-nanosecond pulses at 1064 nm and 532 nm at 20 Hz — to validate the detection pipeline, recovering the known source and providing a calibration-positive benchmark that defines the sensitivity floor for this channel. CALIOP-style recovery belongs to this channel's `calibration_positive` control set, not to the time-domain photometry channel.

### 3.6 Radio Layer
Breakthrough Listen Data Release 1.0 contains almost 1 PB of data from the 1,327-star analysis with public processing tools including blimpy and turboSETI (Berkeley SETI Research Center). COSMIC had observed more than 950,000 unique VLASS pointings by September 2024 with a postprocessing pipeline targeting narrowband signals (COSMIC arXiv).

**Radio non-detections are only meaningful relative to exposure, frequency coverage, drift-rate coverage, sensitivity, and target geometry.** The graph stores `radio_coverage_confidence` and `coverage_mask_radio` separately from `radio_candidate_z`. A source with no Breakthrough Listen or COSMIC coverage is not a negative result; it carries no radio evidence in either direction.

The signal model extends beyond narrowband spikes: stellar plasma near the transmitter — density fluctuations, stellar winds, and coronal mass ejections — can broaden a narrowband signal and reduce peak spectral density used by conventional pipelines. This effect is compounded for active M-dwarf systems, which comprise approximately 75% of Milky Way stars. A β-convolutional variational autoencoder applied to 820 nearby stars in GBT Breakthrough Listen data across more than 480 hours returned eight candidate signals for re-observation while reducing the RFI false-positive rate. Structured signal templates for archival reanalysis include plasma-broadened narrowband, frequency combs, cyclostationary modulation, chirped/hopping patterns, and low-duty-cycle burst trains.

ABACAD directional logic suppresses broad classes of local RFI by requiring on-source presence and off-source absence, but promoted candidates still require checks against sidelobes, satellite trajectories, backend artifacts, known transmitter catalogs, and time-local interference patterns.

### 3.7 Exoplanet Architecture Layer
N-body simulations demonstrate that mean-motion resonance chains encoding mathematical sequences can remain stable over 10 Gyr of main-sequence evolution and remain detectable through post-main-sequence phases. The pipeline computes adjacent orbital period ratios for all multiplanet systems in the NASA Exoplanet Archive, applies confounder penalties for natural disk-migration resonance families (2:1, 3:2, 4:3), and scores for sequence resemblance to primes, Fibonacci, and triangular numbers. This layer promotes only when the host star has elevated scores in at least one independent modality.

### 3.8 Geometry Priors
Geometry priors are not measurement modalities. They are pre-registered timing and observability bonuses that enter the score as \(G\), not as modality scores in the independence matrix \(I_{ij}\).

**SETI Ellipsoid.** The Gaia-based SN 1987A implementation found an average of 734 stars per year within 100 pc intersecting the ellipsoid boundary. The TESS follow-up identified 32 targets in the continuous viewing zone with uncertainties better than 0.5 light-year and found no anomalous signatures in those light curves. This null result over 32 pre-selected targets provides the base-rate calibration for the geometry bonus: the prior probability of a signal coinciding with ellipsoid crossing at the 32-target / 0-detection level establishes the baseline against which any future detection must be scored. Additional anchor events — SN 1006, Cassiopeia A, Eta Carinae 1843, and major GRBs with distance constraints — define non-overlapping ellipsoid geometries with distinct stellar populations. The `GeometryPrior` bonus applies only when the event window is pre-registered before any candidate is identified.

**Earth Transit Zone.** Kaltenegger and Pepper identified 1,004 main-sequence stars within 100 pc from which Earth would be detectable as a transiting exoplanet. ETZ membership is mutual observability as a Bayesian prior. Dynamic time windows — which ETZ stars can observe Earth's transit now versus within the past millennium — combine with ellipsoid event timing for joint geometry scores.

***
## 4. Lead Score
\[
\text{LeadScore} = \sum_i w_i q_i E_i + \lambda \sum_{i,j} I_{ij} \min(q_i E_i,\ q_j E_j) + G + R - \boldsymbol{\beta}^\top \mathbf{P} - D
\]

Where:
- \(E_i\) = calibrated evidence for modality \(i\) (Section 5.1)
- \(q_i\) = modality quality / coverage confidence (Section 5.2)
- \(I_{ij}\) = empirical independence weight (Section 5.3)
- \(G\) = pre-registered geometry prior bonus (SETI Ellipsoid, ETZ)
- \(R\) = repeatability bonus (signal confirmed across epochs)
- \(\boldsymbol{\beta}^\top \mathbf{P}\) = confounder penalty (Section 5.4)
- \(D\) = data quality penalty (RUWE, astrometric excess noise, photometric flags)

The cross-modal term uses \(\min(q_i E_i,\ q_j E_j)\) rather than \(\min(E_i, E_j)\) to prevent a low-coverage modality from amplifying a high-evidence one. A shallow radio exposure should not boost a strong IR signal.

***
## 5. Methods Core
### 5.1 Score Calibration
Raw anomaly scores across WISE residuals, radio candidates, light-curve anomalies, astrometric residuals, and resonance scores are not commensurate: they have different tail distributions, different selection functions, and different missingness patterns. The Lead Graph converts each to a calibrated empirical tail probability before any cross-modal combination.

For modality \(i\), define a matched control population \(C_i\) stratified by stellar type, G-band magnitude, distance bin, Galactic latitude, survey coverage tier, and data quality. Convert raw anomaly score \(s_i\) to an empirical tail probability using the Laplace-smoothed rank estimator:

\[
p_i = \frac{1 + \sum_{c \in C_i} \mathbb{1}(s_c \ge s_i)}{1 + |C_i|}
\]

Then convert to a log-evidence score:

\[
E_i = -\log_{10}(p_i)
\]

A source at the 99th percentile of its matched control population scores \(E_i = 2\). A source at the 99.9th percentile scores \(E_i = 3\). The scale is commensurate across modalities, interpretable without domain knowledge of individual score distributions, and resistant to heavy-tailed outliers in any single channel.

### 5.2 Coverage Handling
Each source carries a coverage mask and a continuous quality weight:

\[
\mathbf{M} = (m_{\text{WISE}},\ m_{\text{TD}},\ m_{\text{spec}},\ m_{\text{pulse}},\ m_{\text{BL}},\ m_{\text{COSMIC}},\ m_{\text{exo}})
\]

where \(m_i = 1\) indicates usable data in modality \(i\) meeting minimum S/N and completeness thresholds. The quality weight is \(q_i = m_i \cdot c_i\), where \(c_i\) is a continuous coverage confidence score (exposure depth, frequency coverage fraction, photometric baseline length, etc.). **Unobserved modalities do not contribute positive or negative evidence.** Published rankings are stratified by coverage class: a source covered only by WISE and TESS is ranked within that coverage class and not penalized against sources with full radio coverage.

Coverage absence is never negative evidence. Quiet-negative controls are evaluated only within modalities for which they have usable coverage.

### 5.3 Independence Weighting
The graph does not assume independence; it estimates independence from control populations and releases the independence matrix as a public, version-tracked artifact. For modality pair \((i, j)\):

\[
I_{ij} = 1 - \left| \rho_{ij}^{\text{null}} \right|
\]

where \(\rho_{ij}^{\text{null}}\) is the Spearman rank correlation between \(E_i\) and \(E_j\) across quiet-negative and contaminant-positive control sources. High correlation in controls indicates shared confounders dominate both channels; independence weight is low.

| Modality pair | Expected \(I_{ij}\) | Reason |
|---|---|---|
| WISE All-Sky + AllWISE | Low | Same detector photometric system |
| Kepler transit anomaly + TESS transit anomaly | Low–Medium | Same photometric method; possible shared instrumental systematics |
| Spectral residual + time-domain photometry | Medium | Same telescope band but different physical phenomenon |
| WISE W4 excess + BL radio candidate (directional) | High | Orthogonal systematic error sources, different instruments |
| Gaia astrometric residual + ZTF dipper | High | Astrometry vs. flux, different instruments |
| Geometry prior (SETI Ellipsoid / ETZ) | Enters as \(G\), not \(I_{ij}\) | Pre-registered timing prior; not a sensor measurement |
| `distance_gspphot_pc` discrepancy | Not independent | GSP-Phot consumes Gaia parallax; excluded from independence calculation |

These are initialization values. The empirical independence matrix is recomputed after each catalog version using updated control sets.

### 5.4 Confounder Model
Confounders are not collapsed early. Each source carries a confounder probability vector:

\[
\mathbf{P} = (P_{\text{YSO}},\ P_{\text{AGN}},\ P_{\text{blend}},\ P_{\text{HOT DOG}},\ P_{\text{debris}},\ P_{\text{binary}},\ P_{\text{crowding}},\ P_{\text{badflag}},\ P_{\text{QSO}},\ P_{\text{galaxy}})
\]

The ConfounderPenalty is:

\[
\text{ConfounderPenalty} = \boldsymbol{\beta}^\top \mathbf{P}
\]

The \(\boldsymbol{\beta}\) weights are initialized from domain knowledge — confirmed Hephaistos candidate G contamination sets a high \(\beta_{\text{HOT DOG}}\) and \(\beta_{\text{blend}}\) for IR-excess candidates — and can be calibrated against the contaminant-positive control set. The full vector is stored per source in the output schema; individual components are inspectable and independently challengeable.

### 5.5 False-Discovery Control
The leaderboard is a multiple-testing machine. For each coverage class \(g\), the graph converts LeadScore into an empirical lead-level p-value by comparing each source against held-out quiet-negative and contaminant-control objects in the same coverage class:

\[
p^{\text{lead}}_k =
\frac{1 + \sum_{c \in C_{0,g}} \mathbb{1}(L_c \ge L_k)}
{1 + |C_{0,g}|}
\]

where \(L_k\) is the LeadScore for source \(k\), and \(C_{0,g}\) is the held-out null/control population for coverage class \(g\). Benjamini-Hochberg correction is then applied to these empirical p-values, not to raw LeadScore values, producing `fdr_q_value_within_coverage_class`. The output schema includes both `lead_empirical_p_value_within_coverage_class` and `fdr_q_value_within_coverage_class` for each source. Results should be interpreted within coverage class, not pooled across classes with different modality availability.

***
## 6. Benchmarking and Controls
A ranking system without recovery tests and contaminant controls is an anomaly generator, not a scientific instrument. The Lead Graph requires the following control sets:

| Control type | Purpose | Examples |
|---|---|---|
| `calibration_positive` | Pipeline must recover known signals at correct sensitivity floor | CALIOP pulses for optical pulse channel; injected broadened-narrowband and comb signals in BL data; injected SED excesses in WISE photometry; injected transit depth perturbations in Kepler light curves |
| `contaminant_confirmed` | Pipeline must detect anomaly but ConfounderPenalty must suppress LeadScore | Hephaistos candidate G (confirmed background AGN at high resolution); known AGN; known YSOs; known debris disks; confirmed RFI events |
| `contaminant_suspected` | Stress-test contaminants pending equivalent high-resolution follow-up | Hephaistos candidates A and B (suspected from radio-source offsets); other offset-background cases |
| `quiet_negative` | Pipeline should score near zero in all covered modalities | Clean Gaia single-star solutions (RUWE < 1.2); no WISE excess in covered bands; no TESS/ZTF variability in covered epochs; confirmed radio null result with adequate exposure; no companion or confounder flags; evaluated only within modalities for which usable coverage exists |
| `synthetic_injection` | Measures per-modality sensitivity and recovery rate \(\epsilon_i(s)\) | Injected radio signals at controlled FWHM; injected transit residuals at controlled depth/asymmetry; injected SED profiles at controlled temperature; injected WISE confusion events |

The VERITAS/CALIOP result is the model for `calibration_positive`: the pipeline recovered a known space-based pulsed laser even though the accompanying technosignature search was a null result, validating the optical pulse channel's sensitivity floor independently of any claimed detection. Every modality channel must have a `calibration_positive` analog before its \(E_i\) values enter the LeadScore.

***
## 7. Output Schema
### Source Table Columns
| Column | Description |
|---|---|
| `gaia_source_id` | Gaia DR3 source identifier |
| `ra` / `dec` | ICRS coordinates |
| `parallax_over_error` | Astrometric S/N |
| `distance_parallax_pc` | Geometric distance (Gaia parallax) |
| `distance_gspphot_pc` | Spectrophotometric distance (GSP-Phot, parallax-dependent) |
| `distance_photometric_noparallax_pc` | Independent photometric/spectroscopic distance (external) |
| `distance_discrepancy_noparallax_z` | Tension: `distance_parallax_pc` vs. independent estimate |
| `ruwe` | Astrometric goodness-of-fit |
| `astrometric_excess_noise` | Residual astrometric noise |
| `phot_bp_rp_excess_factor` | Photometric contamination indicator |
| `non_single_star_flag` | NSS table membership |
| `qso_probability` | Gaia DSC quasar classifier |
| `galaxy_probability` | Gaia DSC galaxy classifier |
| `wise_xm_angular_distance` | AllWISE best-neighbour angular offset |
| `wise_xm_n_neighbours` | AllWISE crossmatch neighbour count |
| `wise_w3w4_residual_z` | SED-subtracted W3/W4 raw z-score |
| `ir_evidence` | Calibrated \(E_i\) for IR modality |
| `ir_coverage_confidence` | IR modality \(q_i\) |
| `time_domain_evidence` | Calibrated \(E_i\) for TESS/Kepler/ZTF |
| `time_domain_coverage_confidence` | Time-domain \(q_i\) |
| `spectra_residual_evidence` | Calibrated \(E_i\) for optical spectral residual (v0.4+) |
| `spectra_coverage_confidence` | Spectral \(q_i\) (v0.4+) |
| `optical_pulse_evidence` | Calibrated \(E_i\) for nanosecond pulse channel |
| `optical_pulse_coverage_confidence` | Pulse channel \(q_i\) |
| `coverage_mask_radio` | Radio coverage binary flag |
| `coverage_mask_tess` | TESS coverage binary flag |
| `coverage_mask_wise` | WISE coverage binary flag |
| `coverage_mask_spectra` | Spectra coverage binary flag |
| `coverage_confidence` | Composite coverage quality |
| `radio_candidate_z` | BL/COSMIC directional candidate raw z |
| `radio_evidence` | Calibrated \(E_i\) for radio modality |
| `radio_coverage_confidence` | Radio \(q_i\) |
| `sn1987a_ellipsoid_score` | SN 1987A ellipsoid timing bonus (pre-registered) |
| `cassA_ellipsoid_score` | Cas A ellipsoid timing bonus (pre-registered) |
| `etz_flag` | Earth Transit Zone membership |
| `etz_dynamic_window` | Current/recent Earth transit observability |
| `orbital_sequence_score` | Resonance encoding score (multiplanet hosts) |
| `confounder_vector` | JSON: \(\mathbf{P}\) component scores |
| `data_quality_penalty` | \(D\): RUWE, astrometric flags composite |
| `lead_score` | Final composite score |
| `lead_empirical_p_value_within_coverage_class` | Empirical p-value from LeadScore vs. held-out controls within coverage tier |
| `fdr_q_value_within_coverage_class` | Benjamini-Hochberg q-value within coverage tier |
| `coverage_class` | Coverage tier for stratified ranking |
| `followup_class` | Recommended next action |

### Follow-Up Classes
| Class | Trigger |
|---|---|
| `radio_reobserve` | \(E_{\text{radio}} > \theta_r\); directional checks passed; elevated lead score |
| `optical_spectra_reobserve` | Spectral residual evidence high; co-elevated IR or radio modality (v0.4+) |
| `ir_followup` | IR evidence high; confounder vector low; angular offset clean; HOT DOG probability low |
| `tess_ztf_monitoring` | Anomalous individual transit or ZTF dipper event |
| `needs_human_review` | High lead score; ambiguous confounder status |
| `discard_confounded` | High raw anomaly z; high ConfounderPenalty |

***
## 8. Public Release Artifacts

```
lead_graph_catalog_v1.csv          — ranked source table (all schema columns)
modality_scores.parquet            — per-source raw and calibrated E_i per modality
confounder_vectors.parquet         — per-source P vector with component scores
independence_matrix.csv            — I_{ij} for all modality pairs, version-tracked
coverage_masks.parquet             — coverage confidence q_i per source per modality
fdr_by_coverage_class.csv          — empirical p-values and BH q-values by coverage tier
distance_models.parquet            — parallax, GSP-Phot, and no-parallax distance estimates
controls/
    calibration_positive/          — CALIOP, injected radio/optical/SED signals
    contaminant_confirmed/         — Hephaistos G, known AGN/YSOs/debris disks, confirmed RFI
    contaminant_suspected/         — Hephaistos A, B; other offset-background cases
    quiet_negative/                — clean main-sequence control stars (coverage-stratified)
    synthetic_injection/           — injected signals at controlled parameters
pre_registration/                  — frozen modality definitions and event-window specs
                                   — before any candidate is selected; version-locked
notebooks/                         — reproduction notebooks per modality
src/pharos/                        — scoring code (Python, versioned, tested)
docs/model_card.md                 — what the score means and does not mean
```

The `pre_registration/` directory is the scientific hygiene anchor. Geometry prior windows (SETI Ellipsoid event epochs, ETZ observability windows) are frozen before any archival data is queried. Any geometry bonus applied to a candidate must reference a pre-registered event definition.

***
## 9. Build Sequence

### v0.1 — IR / Astrometric Confounder Benchmark
*Goal:* Reproduce and improve IR-excess lead suppression relative to Project Hephaistos.

*Inputs:* Gaia DR3 source table; `gaiadr3.allwise_best_neighbour` crossmatch; 2MASS photometry; known debris disks, YSOs, AGN, and the Hephaistos confirmed-contamination case (candidate G) plus suspected-contamination cases (candidates A, B) as contaminant controls.

*Pass criterion:* The graph must demote Hephaistos candidate G into `discard_confounded` based on the confirmed background AGN evidence, and must demote candidates A and B into `discard_confounded` or `needs_human_review` based on suspected background-source contamination. The remaining four Hephaistos candidates must not receive top-tier `ir_followup` status unless their WISE centroids, crossmatch quality, local background environment, and independent modality checks survive inspection. If the graph cannot pass this stress test, the confounder model is not production-ready.

*Outputs:* `ir_evidence`, `wise_confusion_score`, `distance_discrepancy_noparallax_z` (for sources with external spectroscopy), `confounder_vector`, and a ranked IR lead list with empirical p-values and BH q-values within the WISE-coverage class.

### v0.2 — Time-Domain Integration
Add TESS/Kepler per-transit residual scores and ZTF dipper scores. Build `calibration_positive` set for time-domain channel. Confirm that quiet-negative controls score near zero in time-domain modality (within covered epochs only) and that Boyajian's Star processes correctly as a high-anomaly, ambiguous-confounder source that lands in `needs_human_review`, not `ir_followup`.

### v0.3 — Radio Coverage and Candidate Integration
Add Breakthrough Listen coverage masks and candidate scores from BLDR 1.0 and COSMIC VLASS data. Apply structured-signal templates alongside standard turboSETI. Confirm that known RFI events appear in `contaminant_confirmed` control set and are suppressed by ConfounderPenalty. Compute first empirical independence matrix from combined IR + time-domain + radio control sets. **Scope is intentionally limited to radio.** Spectral residuals are deferred to v0.4 to avoid integrating two hard modalities simultaneously.

### v0.4 — Spectral Residual Integration
Add spectral residual channel with Keck HIRES archive as initial input; extend to HARPS and LAMOST as available. Build `calibration_positive` injection set for spectral residuals. Recompute the independence matrix with spectral residuals included.

### v1.0 — Public Cross-Modal Leaderboard
Only after v0.1–v0.4 pass their stated control benchmarks: integrate geometry priors (pre-registered), exoplanet architecture layer, optical pulse channel, full independence matrix recomputed from all controls, and FDR control by coverage class. Publish the catalog with all artifacts.

***
## 10. Future Registered Modalities
The following channels are legitimate extensions. They enter the graph only after their scoring functions, confounders, control sets, and injection-recovery tests are pre-registered and published.

**JWST atmospheric chemistry.** Lin et al. estimate CF4 and CCl3F detection or constraint at roughly 10× terrestrial concentration with approximately 1.7 and 1.2 days of JWST integration respectively under their model assumptions. This modality enters the graph when a pre-registered set of exoplanet spectra has sufficient wavelength coverage, S/N, and atmospheric retrieval metadata to define matched controls and injection-recovery tests.

**Interstellar object triage.** No credible evidence of artificial origin exists for any of the three currently known ISOs. Rubin/LSST will accelerate ISO discovery. The triage checklist — hyperbolic excess, non-gravitational acceleration residuals, spectral reflectance outliers, mid-IR excess, polarimetry anomalies, radio drift rates tied to measured kinematics — is the pre-registration instrument for this modality.

**LIGO megatechnology exclusion limits.** The RAMAcraft framework provides matched-filter templates for linearly-accelerating massive objects suitable for O3/O4 archival strain data. Framing: upper bounds on megatechnology activity in the local galaxy volume, not artifact detection.

**Generalized frequency combs.** Wright's framework provides Planck-comb frequencies derived from universal physical constants as candidate Schelling points; the generalized invariant is compressible structure in frequency space. This modality enters when a comb detector with a defined false positive rate is validated against both calibration-positive and contaminant-positive controls in radio and optical archival data.

***
## Positioning
The manuscript does not read: "Here are all the ways technology might show up in astronomical data." It reads: "Here is a versioned public instrument for converting archival anomalies into disciplined follow-up priorities." The first publishable artifact is not the full cross-modal catalog; it is the IR/Astrometric Confounder Benchmark (v0.1) that demonstrates the system can demote seductive false positives before it promotes anything.

Most papers in this space ask: *What should we search for?* This paper asks: *Which public sky objects deserve follow-up after independent archival anomalies and known confounders are scored together?* That is the position. The paper wins by controlling the re-observation queue, not by proposing the most interesting signal hypothesis.

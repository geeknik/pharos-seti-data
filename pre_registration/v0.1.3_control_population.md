# Pre-Registration: Pharos v0.1.3 — Hardened Quiet-Negative Control Population

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** quiet-negative IR/astrometric control acquisition and immutable release only

**Supersedes:** the quiet-negative population acquisition procedure in [`v0.1_ir_benchmark.md`](v0.1_ir_benchmark.md) Section 6 and the v0.1.2 implementation assumptions for that procedure; it does not change v0.1/v0.1.2 scoring, model, confounder, X-ray, or follow-up rules

**Pilot disclosure:** the 2026-08-05/06 v0.1.2 hardened pilot was observed before this document was authored; see [`failed_attempts/v0.1.2_hardened_control_population.md`](failed_attempts/v0.1.2_hardened_control_population.md)

This document becomes immutable only after its exact byte SHA-256 and size are appended to [`FROZEN.md`](FROZEN.md) and the document plus freeze record are committed. No v0.1.3 query, reacquisition, checkpoint creation, exclusion request, model fit, or pass-criterion evaluation may occur before that freeze commit. After freeze, correction is by a versioned superseding pre-registration, never by editing this file.

The pilot informed the engineering design and exposed a prior registration deviation. It did **not** set or tune a scientific threshold in this document. v0.1.3 requires a new deterministic acquisition from zero after freeze; pilot rows, cursors, response tables, checkpoints, BP/RP medians, exclusions, and final controls are prohibited inputs.

---

## 1. Claim Boundary and Prohibited Work

v0.1.3 will produce one validated quiet-negative control release for the WISE-only coverage class. It does not fit a contaminant-family model, estimate a coefficient, calibrate evidence, compute a LeadScore/FDR value, rank a target, classify a Hephaistos candidate, or make a technosignature claim.

No later model may consume this release merely because v0.1.3 passes. A separate, prospectively frozen modeling pre-registration must name the exact registered v0.1.3 final-manifest digest, define train/calibration/test leakage controls, and authorize the model's use before any fit or threshold evaluation.

The release supports later matched, coverage-stratified calibration. It is not a representative sample of Gaia DR3, the Milky Way, or all nearby stars. A source absent from the release is not negative evidence.

No implementation may use pilot results to change a gate, quota, bin width, exclusion vocabulary/radius, minimum count, resource bound, retry-dependent selection rule, or pass criterion. Any such change requires v0.1.4 or later and a full reacquisition.

---

## 2. Threat Model

### 2.1 Protected assets

- frozen pre-registration bytes and digest;
- selected Gaia source identities and deterministic parent order;
- exact remote request/response evidence and exclusion decisions;
- raw checkpoint, intermediate parent, final control, and manifest bytes;
- raw-producer and release-producer software provenance;
- dependency lock and source-tree identities;
- archive credentials, if used; and
- the distinction between quarantined data and a trusted release.

### 2.2 Trust boundaries

All remote catalog responses, response metadata, uploaded tables, YAML, Parquet metadata, manifests, cache files, filesystem paths, environment values, and command-line values are untrusted. Boundaries are:

1. network stream to bounded decompressor;
2. decompressed bytes to strict table parser/schema validator;
3. validated raw response to deterministic normalizer;
4. normalized response to checkpoint/intermediate derivation;
5. checkpoint producer to release producer;
6. staging directory to immutable publication directory;
7. release manifest to downstream loader; and
8. secret store to authenticated HTTPS client.

Remote strings and artifact fields may never become executable code, a shell command, an import path, or an unconstrained filesystem path. Network clients use HTTPS with certificate validation and the exact endpoints registered in Sections 6 and 18. Credentials are never stored in the repository, artifacts, logs, exceptions, or query evidence.

---

## 3. Exact Parent Population and Sampling Plan

### 3.1 Catalogs

The acquisition joins:

- Gaia DR3 `gaiadr3.gaia_source`;
- Gaia DR3 `gaiadr3.allwise_best_neighbour` to Gaia-hosted `gaiadr1.allwise_original_valid`; and
- Gaia DR3 `gaiadr3.tmass_psc_xsc_best_neighbour` to Gaia-hosted `gaiadr1.tmass_original_valid`.

Catalog names and projected columns are frozen in the request evidence. A table/release substitution, even if described as newer or equivalent, requires a new registration.

### 3.2 Twenty-four cells

The parent uses 24 disjoint coarse sky cells. Galactic longitude is divided into these half-open intervals in degrees:

```text
[0,30), [30,60), [60,90), [90,120), [120,150), [150,180),
[180,210), [210,240), [240,270), [270,300), [300,330), [330,360)
```

Each interval is split into `north` (`b > +20 degrees`) and `south` (`b < -20 degrees`). The canonical order is longitude ascending and, within each interval, north then south. Cell identifiers are exactly `lLLL-UUU-north` and `lLLL-UUU-south`, zero-padded as in `l000-030-north`.

### 3.3 Exact quotas

Let target `N = 55,000`, cell count `K = 24`, `base = N // K`, and `remainder = N % K`. In canonical cell order:

```text
quota[i] = base + 1 if i < remainder else base
```

Therefore `base = 2,291`, `remainder = 16`, and the fixed allocation is **16 cells × 2,292 plus 8 cells × 2,291 = 55,000**. This corrects the non-authoritative earlier verbal summary of 12 cells at each quota, which totaled 54,996. No cell may borrow from, top up, or substitute for another cell.

### 3.4 Deterministic selection

Each cell starts at cursor `source_id = 0`. Pages use at most 500 requested rows and exactly:

```text
WHERE source_id > :previous_cursor
  AND l >= :longitude_min
  AND l < :longitude_max
  AND (b > 20.0 for north OR b < -20.0 for south)
ORDER BY source_id ASC
```

After a validated non-empty page, the cursor becomes that page's greatest source ID. A page may not overlap a prior page, skip a returned eligible row, change order, or cross a cell boundary. A cell exhausting before quota fails the attempt. Acquisition order is round-robin over incomplete cells in canonical order; the release parent order is canonical cell order then ascending source ID, independent of response timing.

The planned request count is exactly 120 Gaia pages: five pages per cell (four 500-row pages plus one 292- or 291-row page). Retries repeat the identical query and do not advance a cursor until one validated response is durably recorded.

Logical Gaia request order and canonical parent order are distinct. Logical sequence `gaia-0000` through `gaia-0119` follows five round-robin sweeps of the 24 canonical cells. Each decoded page must contain exactly its requested number of rows, strictly increasing by source ID, with every ID greater than the request cursor. A zero or short page is a fatal cell-exhaustion result; it is not retried, padded, or followed by a cursor skip. The canonical parent is then stably reordered by `(cell_ordinal ASC, gaia_dr3_source_id ASC)`. Both the request-order semantic hash and canonical-parent semantic hash are recorded.

### 3.5 Sampling limitation

This plan balances only 30-degree Galactic-longitude/hemisphere cells. It does not select uniformly within a cell: Gaia `source_id` ordering may encode scan/spatial structure. No inverse-probability, all-sky prevalence, or representativeness claim is permitted. Downstream use must be matched and stratified within the registered WISE-only coverage class.

---

## 4. Frozen Eligibility Gates

Every projected column is explicit. Missing, extra, duplicated, or reordered columns fail closed. Source identifiers must be unique positive 64-bit integers. Coordinates and required numeric values must be finite and within the domains below.

### 4.1 Gaia gates

Every acquired row must satisfy:

- `parallax_over_error >= 5.0`;
- `parallax > 0` and `parallax >= 5.0` milliarcseconds, corresponding to `1000 / parallax <= 200` pc;
- finite `phot_g_mean_mag` in `[-10.0, 18.0]` and finite `phot_bp_rp_excess_factor` in `[0.0, 100.0]`;
- finite, strictly positive `parallax_error` and finite `parallax`, `parallax_over_error`, and `ruwe`;
- `ruwe < 1.2`;
- `duplicated_source = false`;
- `non_single_star = 0`;
- `classprob_dsc_combmod_galaxy < 0.10`;
- `classprob_dsc_combmod_quasar < 0.10`;
- `galactic_l` in `[0, 360)` and the registered cell's exact longitude interval;
- `galactic_b > 20.0` for north or `< -20.0` for south;
- finite `teff_gspphot` in `[1.0, 100000.0]` K; and
- finite RA in `[0,360)` and Dec in `[-90,90]`.

`teff_gspphot` is explicitly required so every row supports the frozen stellar-temperature stratification. It remains parallax-dependent GSP-Phot metadata and is not an independent anomaly modality.

### 4.2 AllWISE gates

Every acquired row must have:

- exactly one Gaia AllWISE best neighbour and zero mates;
- best-neighbour angular distance in `[0, 1.5]` arcseconds;
- a non-empty AllWISE designation;
- W1, W2, and W3 magnitudes and positive magnitude uncertainties;
- derived `SNR = 1.0857 / magnitude_error`, internally consistent within relative tolerance `1e-9` and absolute tolerance `1e-12`;
- W1 SNR at least 5.0, W2 SNR at least 5.0, and W3 SNR at least 3.0;
- `cc_flags` absent or exactly `0000`; and
- `ext_flg` absent or exactly `0`.

The exact uncertainty ceilings implied by the formula are inclusive. A stored SNR inconsistent with the stored uncertainty fails closed even when both independently clear their thresholds.

### 4.3 Optional W4 rule

W4 is optional and covered only at SNR at least 2.0. Its magnitude, uncertainty, and derived SNR form one triple:

- a complete, finite triple with positive uncertainty and internally consistent SNR is retained only when SNR is at least 2.0;
- a catalog-missing triple, a well-formed partial triple, or a complete valid triple below SNR 2.0 is canonically represented as three nulls; and
- a partial or complete triple containing a nonnumeric/non-finite value, nonpositive uncertainty, negative SNR, or inconsistent SNR fails closed rather than being normalized to absence.

Persisted artifacts must already use the canonical all-present or all-null representation. Loaders do not repair them.

### 4.4 2MASS gates

Every acquired row must have:

- exactly one retained 2MASS best-neighbour row for the Gaia source;
- angular distance in `[0, 1.5]` arcseconds;
- non-empty designation;
- finite Ks magnitude; and
- finite, strictly positive Ks uncertainty.

J and H values may be null when the catalog reports them missing; any present value must satisfy the strict registered numeric/string schema.

For each of J and H, magnitude and uncertainty are an all-present or all-null pair. A present magnitude must be finite; its uncertainty must be finite and strictly positive. A partial pair, nonnumeric value, infinity, NaN represented as a value rather than null, or nonpositive present uncertainty fails. Ks magnitude and uncertainty are always present, finite, with strictly positive uncertainty.

---

## 5. Deterministic BP/RP Parent Derivation

The complete 55,000-row joined parent is acquired and placed in canonical parent order before any BP/RP median is computed. `phot_g_mean_mag` and `phot_bp_rp_excess_factor` are IEEE-754 binary64 values. For each row:

```text
gmag_bin_lower = floor(phot_g_mean_mag * 2.0) / 2.0
bp_rp_excess_bin_median = median(phot_bp_rp_excess_factor in that parent bin)
bp_rp_excess_delta = phot_bp_rp_excess_factor - bp_rp_excess_bin_median
```

A bin is the half-open interval `[k/2, (k+1)/2)` for integer `k`; the admitted endpoint `G = 18.0` belongs to `[18.0,18.5)`. Within a bin, values are sorted ascending as finite binary64. For odd count the median is the middle value. For even count it is `(lower_middle + upper_middle) / 2.0`, evaluated in binary64 round-to-nearest, ties-to-even. Derived columns are binary64. A row survives exactly when binary64 `abs(bp_rp_excess_delta) <= 0.1`. The median is computed over the complete 55,000-row parent, not per page, cell, retry, or preliminary subset. The BP/RP survivor artifact preserves parent order and records the derived bin, median, and delta.

The external-exclusion queries receive only BP/RP survivors. This parent choice is exact and must be proved by the request-index input hashes.

---

## 6. Frozen External Exclusions

### 6.1 SIMBAD

The endpoint is exactly `https://simbad.cds.unistra.fr/simbad/sim-tap`. Source-disjoint uploads contain at most 500 BP/RP survivors in parent order. The server-side discovery cone is prospectively fixed at **30.1 arcseconds**, strictly larger than the scientific exclusion radius, so server-boundary rounding cannot omit a true 30.0-arcsecond match. The query returns matched ICRS coordinates and the server-reported distance for every discovered relation. The local registered spherical function then recomputes separation and retains exactly those rows with local binary64 separation `<= 30.0` arcseconds. It retains only this fixed vocabulary:

```text
YSO: Y*O, Or*, TT*, Ae*, HH, out
AGN: AGN, SyG, Sy1, Sy2, rG, LIN, QSO, Bla, BLL
```

The exact query text is frozen and stored per request. `maxrec` is 50,001; a response with 50,001 or more rows is treated as possibly truncated and fails. At most 100 retained matches per source/catalog are allowed.

The raw validated response is preserved before normalization. Raw server-reported separation is evidence only and cannot make an exclusion decision. After local coordinate validation, registered spherical recomputation, the exact `<= 30.0` cut, and mapping to the frozen exclusion schema, exact duplicate full tuples are removed in stable first-occurrence order. Different object types or matched objects are not duplicates. The normalized per-request artifacts concatenate in request order to form the SIMBAD part of the release exclusions.

### 6.2 Chen debris disks

The endpoint is exactly `https://vizier.cds.unistra.fr/viz-bin/votable`; the catalog is exactly `J/ApJS/211/25/catalog`, identified as the `2021-08-10` release. One request projects exactly `_RA`, `_DE`, and `Name`, in that order, with row limit 10,000. The canonical descriptor, decoded schema, semantic frame, and normalized matcher all use this same column order. A response at the limit fails as possibly truncated. Values must be finite/in-domain and identifiers non-empty.

The complete validated catalog response is preserved as raw response evidence. Direct ICRS catalog coordinates are used without proper-motion correction. Both Chen and SIMBAD local matching use the frozen function `pharos_spherical_sep_arcsec_v1`: CPython `float`/IEEE-754 binary64; `PI = float.fromhex('0x1.921fb54442d18p+1')`; degrees-to-radians evaluated as `(degrees * PI) / 180.0`; unit vector evaluated in field order as `(cos(dec_rad) * cos(ra_rad), cos(dec_rad) * sin(ra_rad), sin(dec_rad))`; `cx = uy*vz - uz*vy`, `cy = uz*vx - ux*vz`, and `cz = ux*vy - uy*vx`, evaluated in that order; `cross_norm = math.sqrt(cx*cx + cy*cy + cz*cz)`; `dot_unclamped = ux*vx + uy*vy + uz*vz`; `dot = min(1.0, max(-1.0, dot_unclamped))`; and `separation = math.atan2(cross_norm, dot) * (180.0 / PI) * 3600.0`. Every named intermediate is stored as binary64 before the next expression. No fused-operation substitution, vectorized fast-math, proper-motion correction, alternate pi constant, or angular-library helper is permitted. The release platform is the exact packaged CPython 3.14.6/macOS-27.0-arm64/OpenSSL 3.6.3 toolchain, with libc/libm build identities and binary hashes recorded; a different platform may validate science using the registered `<= 30.0` decision plus reference fixtures but cannot produce a byte-registered replacement artifact. A match is retained when separation is exactly `<= 30.0` arcseconds. Output order is BP/RP parent rank, separation ascending, UTF-8 bytewise `Name` ascending, then zero-based Chen raw-row index ascending. All matches are retained subject to the 100-per-source/catalog bound; ties are never chosen arbitrarily. Stable match output is normalized to `exclusion_catalog = Chen2014`, `exclusion_class = debris_disk`, and `matched_otype = debris_disk`.

### 6.3 Exclusion relationship

Every normalized exclusion source ID must belong to the BP/RP survivor parent. Exclusion tuples must be exact-schema, bounded strings, finite separations in `[0,30]`, and free of residual exact duplicates. The final controls are exactly:

```text
quiet_negative = bp_rp_survivors minus every unique exclusion source ID
```

No other catalog, heuristic, manual exclusion, or post-hoc deletion is allowed.

---

## 7. Minimum Size and Stratifiability

The release passes only when:

- raw joined parent rows equal exactly 55,000;
- final quiet-negative rows are at least 50,000 and at most 250,000;
- every one of the 24 acquisition cells remains represented after BP/RP and external exclusions;
- every final row has finite temperature, G magnitude, parallax-derived distance, and Galactic latitude needed for the frozen strata; and
- deterministic labels can be produced for the closed coverage domain using: temperature `[1,4000)`, `[4000,5500)`, `[5500,7000)`, `[7000,100000]` K; G bins `[k/2,(k+1)/2)` including `[18.0,18.5)` only at its admitted value 18.0; parallax distance `d = 1000.0/parallax` in `[0,25)`, `[25,50)`, ..., `[150,175)`, `[175,200]` pc; and absolute latitude `(20,30]` or `(30,90]` degrees.

“Stratifiable” means these fields/bins and all acquisition-cell counts are present and reconstructible. It does not assert equal post-exclusion counts, require a post-observation per-cell minimum, or authorize top-up. The frozen v0.1 labels below 10 degrees and from 10 through 20 degrees have zero support by construction; v0.1.3 makes no low-latitude sufficiency or calibration claim. No sparse scientific bin may be silently pooled; later model code must apply its separately frozen matched-control rule.

---

## 8. Per-Request Evidence and Provenance

### 8.1 Required evidence

Every network request has one exact request record and contained evidence artifacts:

- fixed service name and HTTPS endpoint;
- monotonically increasing request index within service;
- exact query/descriptor text artifact and SHA-256;
- exact uploaded/input table artifact and semantic SHA-256 when an upload exists;
- request and receipt timestamps in UTC;
- validated **raw response table** artifact, row count, byte SHA-256, semantic SHA-256, columns, and schema version;
- deterministic **normalized response table** artifact with the same descriptors;
- normalization identifier/version; and
- retry count plus hashes proving that every retry submitted the identical query and input.

A **logical catalog request** is the scientific operation identified by `attempt_id`, service, sequence, exact query, exact parent slice, and expected result rule. A **transport attempt** is a child network operation (`submit`, `poll`, `fetch`, or `sync`) that may fail and retry without changing the logical request. Logical request identity is stable across transport attempts. Every child records its ordinal, phase, timing, outcome, byte counts, expected hostname, connected peer IP/port, leaf-certificate hash, and TLS version in `transport_attempts.parquet`; no failed child may advance scientific state.

Here “raw response” means the first decoded table returned by the client before Pharos normalization, not undocumented HTTP wire bytes. The transport is still bounded and hashed while being received. The raw table preserves SIMBAD duplicate rows and pre-normalization W4 shapes; the normalized table proves exactly what entered derivation.

For Gaia, normalized page rows must equal raw page rows and canonical reordering of the normalized pages must reproduce the 55,000-row parent exactly. For SIMBAD, raw discovery rows may exceed normalized rows only because the frozen local spherical recomputation rejects rows above 30.0 arcseconds and because exact normalized tuples are deduplicated; both reasons and counts are recorded per request. Normalized rows are sorted by BP/RP parent rank, locally recomputed separation, UTF-8 bytewise matched-object ID, and UTF-8 bytewise object type before stable deduplication, and the sum of normalized request rows equals the SIMBAD exclusion-row count. For Chen, one raw catalog response plus the registered spherical local match reconstructs the Chen exclusions.

### 8.2 Reconstructibility

Starting only from the packaged pre-registration, request index, raw response artifacts, and registered normalizers, an offline rebuild must reproduce identical semantic hashes and row order for normalized responses, raw parent, BP/RP survivors, exclusions, and final controls. Under the exact packaged toolchain it must also reproduce artifact byte hashes. A trace containing only hashes without the response artifacts fails this registration.

Query evidence, input tables, and response tables are data only. Loaders never execute the recorded generating command or query text.

---

## 9. Exact Artifact Schemas and Count Relationships

### 9.1 Schema versions

The release registers these exact schema identifiers:

```text
pharos.gaia-decoded-page.v0.1.3
pharos.gaia-normalized-page.v0.1.3
pharos.quiet-negative-raw.v0.1.3
pharos.quiet-negative-bp-rp.v0.1.3
pharos.simbad-upload.v0.1.3
pharos.simbad-decoded-raw.v0.1.3
pharos.chen-decoded-raw.v0.1.3
pharos.quiet-negative-exclusions.v0.1.3
pharos.quiet-negative.v0.1.3
pharos.remote-request-index.v0.1.3
pharos.remote-transport-attempts.v0.1.3
pharos.attempt-state.v0.1.3
pharos.quiet-negative-checkpoint-manifest.v0.1.3
pharos.quiet-negative-manifest.v0.1.3
pharos.quiet-negative-pass-report.v0.1.3
pharos.control-review-attestation.v0.1.3
```

Unknown fields fail closed in manifests and tables. Required column order is part of each schema. Every Parquet artifact embeds `pharos.pre_registration_sha256`, its schema version, producer source-tree SHA-256, and producer lock SHA-256 in file metadata.

### 9.2 Relational invariants

Let `R` be raw candidates, `B` BP/RP survivors, `X` normalized exclusion rows, `U` unique source IDs in `X`, and `C` final controls. The manifest must prove:

```text
|R| = 55,000
|R| >= |B| >= |C| >= 50,000
U is a subset of source_ids(B)
source_ids(C) = source_ids(B) - U
|C| = |B| - |U|
|X| >= |U|
source_ids(C) intersect U = empty
```

Raw, BP/RP, and control IDs are unique. Exclusion IDs may repeat only for distinct exact-schema tuples and never more than 100 times per source/catalog. Per-cell raw counts equal quotas, retained cell counts sum to `|C|`, Gaia normalized response rows sum to `|R|`, and request input chunks exactly partition their registered parent in order without overlap or omission.

The loader recomputes all gates, W4 normalization identity, BP/RP medians/deltas, exclusions, parent order, cell membership, descriptors, semantic hashes, and relationships. A matching row count or schema alone is insufficient.

---

## 10. Resource, Input, and Filesystem Bounds

All limits are hard fail-closed bounds, not truncation targets:

| Resource | Bound |
|---|---:|
| Gaia/SIMBAD source batch | 500 source rows |
| SIMBAD discovered/retained matches | 100 per source/catalog at each stage; overflow fails |
| SIMBAD `maxrec` sentinel | 50,001 rows; reaching it fails |
| Chen response | fewer than 10,000 rows |
| CLI explicit source IDs | 10,000 |
| Raw candidate rows | 250,000 maximum; v0.1.3 requires exactly 55,000 |
| Final control rows | 250,000 maximum; 50,000 minimum |
| Exclusion rows | 5,000,000 maximum |
| Compressed/wire response body | 33,554,432 bytes per transport attempt |
| Decompressed response body | 67,108,864 bytes per request |
| Materialized deep table memory | 134,217,728 bytes per request |
| Simultaneously live response-table memory | 268,435,456 bytes per process |
| Whole-process resident memory | 1,073,741,824 bytes |
| YAML file | 1,048,576 bytes |
| Individual Parquet file | 2,147,483,648 bytes |
| Parquet footer | 16,777,216 bytes |
| Parquet key/value metadata | 1,048,576 bytes |
| Parquet columns / row groups / nesting | 64 / 1,024 / flat only |
| Parquet column-chunk declared compressed / uncompressed bytes | 67,108,864 / 134,217,728 per chunk |
| Parquet data-page compressed / uncompressed bytes | 16,777,216 / 33,554,432 per page |
| Parquet page-header bytes | 65,536 per page |
| Bounded parser allocator | 268,435,456 bytes total live allocations |
| Parser worker hard virtual-address-space limit | 1,073,741,824 bytes before parser import/use |
| Manifest/request-index text scalar | 4,096 UTF-8 bytes |
| Catalog/exclusion text field | 512 UTF-8 bytes |
| Query artifact | 65,536 UTF-8 bytes |
| Total UTF-8 string payload per decoded response | 33,554,432 bytes |
| Files in one release tree | 2,048 regular files |
| Total release/staging bytes | 4,294,967,296 bytes |
| Relative path / filename component | 240 / 180 UTF-8 bytes |
| Logical catalog requests | `120 + ceil(BP/RP rows / 500) + 1`, at most 231 |

Before any request is sent, its source batch, query bytes, upload schema, upload row count, source-ID order/uniqueness, and expected-output ceiling are validated. Compressed transfer data must stream through a wire-byte counter and counting decompressor into a mode-0600 bounded spool inside the mode-0700 attempt directory; parsing begins only after both byte bounds pass. Content-Length is not trusted. Every table parser runs in a fresh isolated worker whose hard `RLIMIT_AS` soft and hard values are both set to `1,073,741,824` bytes before importing or invoking PyArrow/Astropy/table parsing; inability to establish and read back that exact limit is fatal. The worker uses a registered bounded Arrow allocator that refuses an allocation when total live allocator bytes would exceed `268,435,456`; it never relies only on a post-allocation RSS observation. Batches are processed and released so the deep-table, simultaneously-live, allocator, address-space, and process-RSS bounds cannot be exceeded. Exceeding any bound fails the attempt; data are not silently truncated, sampled, coerced, or dropped.

YAML aliases, anchors, custom tags, duplicate keys, non-string keys, and unknown keys are rejected before semantic use. Parquet preflight occurs inside the already hard-limited worker: verify file size and terminal magic; read only the bounded footer; parse footer metadata under the bounded allocator; reject more than 64 columns, 1,024 row groups, nested/logical types outside the registered schema, or aggregate metadata over 1,048,576 bytes; then validate every row group's declared row count and every column chunk's file offsets, compressed size, uncompressed size, and end offset against the file boundary and the per-chunk bounds above. Before decompression, the loader walks each column chunk's page headers with a 65,536-byte header cap and rejects any data/dictionary page whose declared compressed or uncompressed size exceeds its page bound or whose byte range escapes the validated chunk. Only after all footer/chunk/page declarations for the next batch pass may buffers be allocated and pages decompressed. Decompressed column buffers and string lengths remain checked during bounded loading. All strings must be valid UTF-8, free of NUL, and used only as data.

Paths in artifacts are non-empty relative POSIX paths with no `..`, no absolute component, and no platform drive/UNC form. Every existing component from release root to target is checked without following symlinks. Inputs and outputs must be regular files; hard-link substitution across the trusted staging boundary and symlink/time-of-check-time-of-use swaps are rejected by descriptor-relative opens plus inode/device verification. The attempt and staging directories are created mode `0700`; files are `0600`. The output directory must not already exist. The exact publication algorithm is: create a unique mode-0700 sibling staging directory using descriptor-relative `mkdirat`; create every payload with `O_CREAT|O_EXCL|O_NOFOLLOW`; flush and `fsync` each payload; `fsync` every payload directory bottom-up; generate the candidate manifest from opened payload descriptors; create `manifest.yaml` last with `O_CREAT|O_EXCL|O_NOFOLLOW`; flush/fsync it; fsync the staging root; verify all opened inode/device pairs and hashes again; then publish the whole staging directory with macOS `renameatx_np(parent_fd, staging_name, parent_fd, final_name, RENAME_EXCL)` and fsync the parent directory. The registered macOS toolchain must demonstrate `RENAME_EXCL` support before acquisition. If that primitive is absent, returns unsupported, crosses a filesystem, or finds a destination, publication fails closed; copy, plain `rename`, pre-check-then-rename, delete-and-retry, and overwrite fallbacks are prohibited. A manifestless partial staging directory is invalid and requires explicit operator quarantine/removal, never automatic reuse.

Network policy is exact. Allowed peers are `gea.esac.esa.int:443`, `simbad.cds.unistra.fr:443`, and `vizier.cds.unistra.fr:443`; DNS results resolving to loopback, link-local, multicast, reserved, unspecified, or private address space fail, and the connected peer IP must be one of the just-validated public answers. TLS 1.3 with SNI, hostname validation, and certificate validation is mandatory. The immutable CA input is the packaged 240,216-byte certifi 2026.07.22 bundle with byte SHA-256 `9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`; any other size or digest fails. Redirect count is zero. At startup the worker rejects any non-empty `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `http_proxy`, `https_proxy`, `all_proxy`, `no_proxy`, `NETRC`, `netrc`, `CURL_HOME`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `AWS_CA_BUNDLE`, `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`, `NODE_EXTRA_CA_CERTS`, `PIP_CERT`, or `GIT_SSL_CAINFO`. HTTP-session `trust_env` is exactly false; proxy auto-discovery, `.netrc`, ambient cookies, OS keychain client identities, and TLS client certificates are disabled. Credentials are anonymous by default. Optional Gaia username/password credentials are read only from the explicit `PHAROS_GAIA_CREDENTIALS` regular file outside the repository with mode `0600`; supplied authentication failure is fatal, and credentials/authorization headers are never forwarded on any redirect or to SIMBAD/VizieR. Every transport record stores the expected hostname, actual peer IP, peer port 443, TLS version, and leaf-certificate SHA-256.

TCP connect and TLS-handshake timeouts are each 10 seconds. HTTP response-header timeout is 60 seconds and successful body-read timeout is 600 seconds. Gaia async logical deadline is 7,200 seconds with 10-second polls and at most 720 poll operations. SIMBAD and Chen logical deadlines are 600 seconds. Submission, fetch, and synchronous operations permit at most three transport attempts with deterministic waits of 5 then 15 seconds; only connection reset, timeout before any response bytes, TLS close-notify loss before bytes, and HTTP 429/502/503/504 are retryable. Schema, short-page, byte-bound, certificate, host, redirect, HTTP 4xx other than 429, or any response-after-bytes error is fatal. Each retry uses identical query/input hashes and a fresh bounded spool.

---

## 11. Producer Provenance and Trusted-Release Registry

### 11.1 Separate producers

The raw acquisition producer and release derivation producer are separately recorded. Each identity contains:

```text
git_commit (full 40-character commit)
source_tree_sha256 (exact `pharos-source-tree-v1` construction in Section 16)
uv_lock_sha256
```

The raw producer performs network acquisition and creates request evidence/checkpoints. The release producer consumes only an exactly trusted raw checkpoint/evidence set and derives BP/RP survivors, exclusions, controls, and the final manifest. They need not be the same commit, and neither may be inferred from the other.

Both producers refuse dirty tracked or untracked files under `src/pharos`, `pyproject.toml`, or `uv.lock`. Dependencies remain exactly pinned and dependency audit results are part of the pass report.

### 11.2 Exact registry workflow

1. **Freeze commit:** hash and record this document in `FROZEN.md`; commit only prospective-registration material.
2. **Implementation commit:** implement v0.1.3 schemas/gates/tests against the frozen digest; all static, unit, negative, and adversarial tests pass from a clean tree.
3. **Fresh Gaia acquisition:** from a clean implementation commit, create a new `attempt_id`, acquire only the 120 Gaia logical pages from cursor zero, construct the canonical 55,000-row parent, and publish a `candidate` raw checkpoint under the quarantine path. No BP/RP derivation or external request occurs yet; no pilot artifact is readable.
4. **Raw candidate commit:** commit the immutable candidate checkpoint/evidence without any review attestation or registry change; record this hash as `candidate_commit`.
5. **Raw review-evidence commit:** from the raw candidate commit, a distinct read-only reviewer validates every request/transport artifact, quota, order/hash, bound, toolchain package, and raw checkpoint manifest. The reviewer writes the exact Section 20.4 raw review attestation under `pre_registration/reviews/v0.1.3/` and commits only that new attestation. This commit must be a direct descendant of `candidate_commit`, is recorded as `review_evidence_commit`, and exists before any registry schema instance may reference it.
6. **Raw registration commit:** from the raw review-evidence commit, an authorized registrar creates one atomic commit whose diff changes only `src/pharos/trusted_control_releases_v013.py` and adds one exact `raw_checkpoint` entry. The candidate manifest remains byte-identical and status `candidate`; trust comes only from the later external registry entry. This is an exact checkpoint allow-list, never a producer-wide allow-list.
7. **Release/external producer:** from the clean raw-registration commit, the release producer loads only that registered Gaia checkpoint, derives `B` by the frozen BP/RP algorithm, then and only then submits the derived SIMBAD batches and the one Chen catalog request. It packages raw/normalized external evidence, derives exclusions and controls, and publishes an immutable final `candidate` directory. The release producer never modifies the registry.
8. **Final candidate commit:** commit the final candidate artifacts without a final review attestation or final-registry change; record this hash as `candidate_commit` for the final role.
9. **Final review-evidence commit:** from the final candidate commit, a distinct reviewer validates the external raw responses, normalizations, spherical matches, parent partition, offline reconstruction, pass report, and all hashes. The reviewer writes the exact Section 20.4 final review attestation and commits only that new attestation. This direct-descendant commit is recorded as `review_evidence_commit` and exists before the final registry entry references it.
10. **Final registration commit:** from the final review-evidence commit, the registrar creates one atomic commit whose diff changes only the registry module and adds one exact `final_release` entry. The final manifest is not rewritten to say registered and does not contain or predict its own byte hash. The registry binds the already committed candidate manifest hash externally.

A release not matching an exact trusted entry is loadable only under the identical clean release-producer tree in explicit review mode and is not public/shipped. Similar hashes, matching producer commits, matching catalog labels, a manifest status, or possession of registry-write access by an acquisition worker never confers trust. Failed/checkpoint artifacts are never auto-loaded. Both three-commit chains—candidate, review evidence, then registry-only—are required; squashing, reordering, or omitting any commit destroys the review boundary and invalidates release status.

---

## 12. Packaged Pre-Registration Binding

The release contains a byte-identical copy of this frozen document named:

```text
pre_registration.v0.1.3.<PREREG_SHA256>.md
```

The release manifest records its relative path, byte count, and SHA-256. Every Parquet file embeds the same digest. The request index, raw checkpoint manifest, final manifest, and pass report also contain it as a required exact field.

The loader verifies the packaged copy against the embedded/manifest digest and, when a repository checkout is present, against `pre_registration/FROZEN.md`. A missing, mutable, mismatched, or unpackaged pre-registration invalidates the release. The digest is inserted only after freeze; placeholders are not valid release metadata.

---

## 13. Freeze and Deviation Policy

After the freeze commit:

- scientific gates, queries, quotas, order, schemas, bounds, normalizers, artifact list, and pass criteria are immutable;
- external downtime pauses or fails an attempt; it does not authorize a substitute service/catalog;
- an implementation bug may be fixed only if semantics remain identical, and every affected artifact is reacquired/rebuilt from zero under a new producer identity;
- no artifact, manifest, response, or cursor is patched in place;
- no failed attempt may be promoted by adding its hashes to a registry; and
- any scientific or schema change requires a superseding pre-registration and a failure/deviation record.

Every attempt records whether it failed before acquisition, during acquisition, during derivation, or during review. The record preserves hashes/counts available at failure while quarantining the incomplete tree.

Each attempt receives one lowercase RFC 4122 UUIDv4 `attempt_id` before any network or file creation. Its append-only local state record permits acquisition/derivation transitions; immutable Git commits and registry entries supply later trust transitions:

```text
initialized
  -> gaia_acquiring
  -> gaia_candidate_complete
  -> bp_rp_derived
  -> external_acquiring
  -> final_candidate_complete
```

The derived trust-state chain is `gaia_candidate_complete -> gaia_candidate_committed -> gaia_review_committed -> gaia_registered -> final_candidate_complete -> final_candidate_committed -> final_review_committed -> final_registered`; candidate, review-evidence, and registry commits prove those transitions without mutating a packaged state file. Any nonterminal local state may transition to terminal `failed`; `failed` and externally derived `final_registered` have no outgoing transition. While state is `gaia_acquiring`, restart is allowed from the latest exactly validated Gaia page checkpoint under the same attempt ID, preregistration digest, raw producer, query template, quota vector, request index, and canonical rows; an incomplete Gaia logical request is discarded and retried with the same logical ID, while a successful Gaia logical request is never reissued. After `gaia_candidate_complete`, Gaia acquisition can never resume: only the immutable, committed, reviewed, and registered Gaia checkpoint may be consumed. While state is `external_acquiring`, fully durable external logical requests whose query/input/raw/normalized artifacts and request/transport records all verify may resume at the next derived BP/RP parent slice. An incomplete, inconsistent, missing, or only partially durable external request fails the entire attempt and requires a new attempt ID; it is not retried across process restart, repaired, or reused. Any mismatch, missing state event, source/config/lock change, or response from another attempt likewise fails and requires a new attempt ID.

---

## 14. Required Controls and Tests

### 14.1 Calibration-positive implementation fixtures

- a fixed tiny 24-cell synthetic source fixture whose quotas, cursors, parent order, BP/RP bins, and final derivation are exactly known;
- valid W1-W4/2MASS boundary rows at the inclusive thresholds;
- a SIMBAD raw fixture with exact duplicates plus local separations immediately below, exactly at, and immediately above 30.0 arcseconds, all discoverable inside the 30.1-arcsecond cone; and
- a Chen fixture evaluated by the exact registered binary64/pi/radian function with known immediately-below, exact-boundary, and immediately-above-30-arcsecond matches.

These validate mechanics only and do not enter the scientific control population.

### 14.2 Negative and adversarial tests

Tests must reject:

- missing, extra, duplicated, or reordered columns;
- duplicate/nonpositive source IDs, non-finite/out-of-domain coordinates, invalid temperature, forged SNR, invalid uncertainties, bad flags, multiplicity, or crossmatch distances;
- malformed/partial W4 values that are not eligible for safe missingness normalization;
- incomplete, overlapping, reordered, cross-cell, cursor-regressing, quota-forged, or response-missing Gaia pages;
- SIMBAD unrequested IDs, unregistered object types, discovery radius other than 30.1 arcseconds, failure to recompute locally, local separation above 30.0, truncation sentinel, per-source match overflow, lost raw duplicates, and missing/reordered input chunks;
- Chen schema/catalog/query/column-order substitution, truncation, invalid coordinate/string values, alternate pi/radian/fast-math semantics, and normalized matches inconsistent with the raw catalog;
- exclusion IDs outside the BP/RP parent, residual duplicate tuples, count mismatches, or excluded IDs retained as controls;
- response hash-only traces without loadable raw/normalized artifacts;
- query/input/response artifact substitution, near-match hashes, wrong producer, dirty tree, lock drift, pre-registration digest mismatch, or pilot checkpoint reuse;
- YAML aliases/anchors/tags/duplicate keys, oversized/decompression-bomb inputs, too-long strings, oversized Parquet metadata/column chunks/page headers/compressed pages/uncompressed pages, false footer sizes/offsets, bounded-allocator exhaustion, failed hard-address-space setup, and excessive file counts;
- path traversal, absolute/UNC paths, symlink ancestors/files, hard-link or inode swaps, existing output directories, unavailable/incorrect no-replace primitive, partial publication, or manifest-before-payload ordering;
- proxy/netrc/CA/client-certificate environment influence, substituted CA bundle, TLS below 1.3, peer-IP/hostname mismatch, private/reserved peer addresses, redirects, or missing leaf-certificate evidence;
- registry entries without candidate then signed review-evidence then registry-only direct-child commits, review attestations not byte-identical to their commits, or registry commits with any non-registry diff; and
- secrets or raw payloads appearing in logs/exceptions.

Fuzz targets cover strict YAML/manifest parsing, relative-path validation, response-schema normalization, optional-W4 normalization, and exclusion normalization. Fuzz runs use explicit memory/time caps.

---

## 15. Pass/Fail Gates

v0.1.3 ships only if all gates pass:

1. **Prospective timing:** every acquisition timestamp and producer commit follows the freeze commit; no pilot input is used.
2. **Exact selection:** 24 canonical cells, exact 16/8 quota allocation, 120 complete Gaia pages, cursor/order proof, and exactly 55,000 unique joined parents.
3. **Eligibility:** loaders re-run and pass every Gaia, AllWISE, W4, 2MASS, temperature, and BP/RP gate.
4. **External exclusions:** exact registered SIMBAD/Chen requests, contained raw/normalized response evidence, complete parent partition, and valid normalized exclusions.
5. **Derivation:** offline reconstruction proves `C = B - U` exactly with registered order/count relationships.
6. **Minimum/stratifiability:** at least 50,000 final rows, all 24 cells represented, and every final row supports registered calibration-bin labels.
7. **Provenance:** raw/release producer identities, lock/source hashes, request evidence, packaged pre-registration, and semantic/byte hashes are complete and mutually consistent.
8. **Registry:** exact reviewed raw-checkpoint and final-release allow-list entries match; near matches fail.
9. **Resource/path safety:** every registered bound and filesystem protection passes negative/adversarial tests.
10. **Determinism:** two offline derivations from the same frozen response-evidence set produce identical row order, normalized semantic hashes, classifications as control/exclusion, and content-addressed payload hashes.
11. **Quality gates:** unit/integration/negative/adversarial/fuzz-smoke tests, Ruff, mypy, package build, dependency audit, and artifact verification pass under the pinned lock.
12. **No model fit:** no model, beta coefficient, calibration, evidence score, FDR, candidate rank, or follow-up class is produced or consumed.

Failure of any gate means v0.1.3 does not ship. The failure is recorded under `pre_registration/failed_attempts/`; this document is not weakened.

---

## 16. Exact Required Output Trees and Software Schemas

Content-addressed `<sha256>` tokens are lowercase byte SHA-256 values. The Gaia-only candidate checkpoint is exactly:

```text
controls/checkpoints/quiet_negative_v0.1.3/<attempt_id>/
    checkpoint_manifest.yaml
    attempt_state.jsonl
    pre_registration.v0.1.3.<sha256>.md
    raw_candidates.<sha256>.parquet
    requests/
        request_index.<sha256>.parquet
        transport_attempts.<sha256>.parquet
        gaia/<sequence>.query.<sha256>.txt
        gaia/<sequence>.raw_response.<sha256>.parquet
        gaia/<sequence>.normalized_response.<sha256>.parquet
    software/
        pharos-seti-data-v0.1.3-source.<sha256>.tar
        uv.lock.<sha256>.txt
        toolchain.<sha256>.yaml
        normalizer_registry.<sha256>.yaml
        ca_bundle.9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f.pem
```

The final candidate directory is exactly:

```text
controls/quiet_negative_v0.1.3/<attempt_id>/
    manifest.yaml
    pass_report.yaml
    attempt_state.jsonl
    pre_registration.v0.1.3.<sha256>.md
    raw_candidates.<sha256>.parquet
    bp_rp_survivors.<sha256>.parquet
    exclusions.<sha256>.parquet
    quiet_negative.<sha256>.parquet
    requests/
        request_index.<sha256>.parquet
        transport_attempts.<sha256>.parquet
        gaia/<sequence>.query.<sha256>.txt
        gaia/<sequence>.raw_response.<sha256>.parquet
        gaia/<sequence>.normalized_response.<sha256>.parquet
        simbad/<sequence>.query.<sha256>.txt
        simbad/<sequence>.input.<sha256>.parquet
        simbad/<sequence>.raw_response.<sha256>.parquet
        simbad/<sequence>.normalized_response.<sha256>.parquet
        chen/0000.query.<sha256>.txt
        chen/0000.raw_response.<sha256>.parquet
        chen/0000.normalized_response.<sha256>.parquet
    software/
        pharos-seti-data-v0.1.3-source.<sha256>.tar
        uv.lock.<sha256>.txt
        toolchain.<sha256>.yaml
        normalizer_registry.<sha256>.yaml
        ca_bundle.9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f.pem
```

`sequence` is a zero-padded four-digit request index beginning at `0000` within each service. Empty response tables are still present as exact-schema zero-row Parquet artifacts. No unspecified file is permitted in the release tree.

The uncompressed source archive is POSIX ustar, with no PAX/GNU extensions. It contains: every Git-indexed regular file under `src/pharos/` at the producer commit; `pyproject.toml`; generated `BUILD-METADATA.json`; and generated `SOURCE-MEMBERS.json`. No other member is permitted. Members are relative regular files sorted by UTF-8 bytewise path, with no link/device/sparse member, uid/gid 0, empty owner/group names, mode `0644`, mtime 0, and exactly two zero end blocks. A path not representable in ustar fails packaging.

`source_tree_sha256` is SHA-256 over the exact `pharos-source-tree-v1` frame built from only the Git-indexed `src/pharos/**` regular files and `pyproject.toml`: ASCII `pharos-source-tree-v1` followed by one NUL; then, for each UTF-8-bytewise sorted path, unsigned little-endian uint64 path-byte length, path bytes, unsigned little-endian uint64 file-byte length, and exact file bytes. Symlinks, submodules, untracked files, missing indexed files, and platform text conversion fail. `uv.lock` has its separate byte hash and is not in this frame.

`SOURCE-MEMBERS.json` is canonical RFC 8785 JSON and must already be byte-canonical. Its serialized top-level key order is therefore exactly `members`, `schema_version`, `source_tree_algorithm`, `source_tree_sha256`; values are respectively an array in tar order, string exactly `pharos.source-members.v1`, string exactly `pharos-source-tree-v1`, and hex64. Each member object has canonical key order `byte_sha256`, `bytes`, `path`, `role`, with values hex64, nonnegative integer, string, and enum `source|build_config|build_metadata`. It lists every tar member except `SOURCE-MEMBERS.json` itself, avoiding self-reference. Unknown, missing, duplicate, noncanonical, or nullable fields fail.

`BUILD-METADATA.json` is canonical RFC 8785 JSON and must already be byte-canonical. Its serialized key order is exactly `build_backend`, `build_requirements`, `producer_git_commit`, `project_name`, `project_version`, `schema_version`, `source_tree_sha256`, `uv_lock_sha256`. Values are respectively string exactly `setuptools.build_meta`; array exactly `setuptools==83.0.0`, `wheel==0.47.0` in that order; hex40; string copied exactly from frozen `pyproject.toml`; string copied exactly from frozen `pyproject.toml`; string exactly `pharos.build-metadata.v1`; hex64; and hex64. Unknown, missing, duplicate, noncanonical, or nullable fields fail.

`toolchain.yaml` is alias-free strict YAML with this exact ordered, non-null schema: `schema_version` = `pharos.toolchain.v1`; `python_implementation` = `CPython`; `python_version` = `3.14.6`; `uv_version` = `0.11.12`; `os_name` = `macOS`; `os_version` = `27.0`; `os_build` = `26A5388g`; `kernel_release` = `27.0.0`; `architecture` = `arm64`; `openssl_version` = `OpenSSL 3.6.3 9 Jun 2026`; `libc_math_runtime_identity` string 1–512 bytes; `libc_math_runtime_sha256` hex64 or null only when the runtime is in the signed dyld shared cache; `dyld_shared_cache_uuid` UUID or null only when the preceding hash is null; `pandas_version` = `3.0.5`; `pyarrow_version` = `25.0.0`; `numpy_version` = `2.5.1`; `pyyaml_version` = `6.0.3`; `astropy_version` = `8.0.1`; `astroquery_version` = `0.4.11`; `certifi_version` = `2026.07.22`; `ca_bundle_bytes` = `240216`; `ca_bundle_sha256` = `9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`; `parquet_format_version` = `2.6`; and `parquet_writer_profile` = `pharos-parquet-v013`. The dyld UUID must be read from the signed running cache, not supplied by an environment variable. Unknown/missing/duplicate keys and unregistered values fail.

`normalizer_registry.yaml` is alias-free strict YAML with exactly: `schema_version` = `pharos.normalizer-registry.v1`; `pre_registration_sha256` hex64; `semantic_hash_algorithm` = `pharos-semantic-frame-le-v1`; and `entries`, an ordered list of exactly five non-null records. Each record contains, in order, `ordinal` int64, `normalization_id` enum, `source_member_path` string, `callable_name` string, `source_file_sha256` hex64, `input_schema` enum, `output_schema` enum, and `parameter_binding_sha256` equal to the frozen preregistration byte hash. The five `(ordinal, normalization_id, source_member_path, callable_name, input_schema, output_schema)` tuples are exactly: `(0, gaia-page-normalize-v013, src/pharos/control_population_v013.py, normalize_gaia_page, pharos.gaia-decoded-page.v0.1.3, pharos.gaia-normalized-page.v0.1.3)`; `(1, bp-rp-derive-v013, src/pharos/control_population_v013.py, derive_bp_rp_survivors, pharos.quiet-negative-raw.v0.1.3, pharos.quiet-negative-bp-rp.v0.1.3)`; `(2, simbad-local-exclusion-v013, src/pharos/control_population_v013.py, normalize_simbad_exclusions, pharos.simbad-decoded-raw.v0.1.3, pharos.quiet-negative-exclusions.v0.1.3)`; `(3, chen-local-exclusion-v013, src/pharos/control_population_v013.py, match_chen_exclusions, pharos.chen-decoded-raw.v0.1.3, pharos.quiet-negative-exclusions.v0.1.3)`; and `(4, final-difference-v013, src/pharos/control_population_v013.py, derive_quiet_negative, pharos.quiet-negative-bp-rp.v0.1.3, pharos.quiet-negative.v0.1.3)`. These strings are evidence and a static allow-list; loaders dispatch through hard-coded ID-to-function mappings and never dynamically import or execute a path/callable string. Unknown, missing, duplicate, reordered, extra, or nullable fields fail.

The candidate manifest is the final filesystem commit marker and binds every listed file, schema, byte/semantic hash, row count, producer, parent relationship, resource limit, cell count, request record, catalog release, timestamp, and frozen pre-registration digest. It does not bind its own byte hash and does not assert registry trust. Only the later registry-only commit binds that immutable manifest hash and changes the external trust state from candidate to registered.

---

## 17. Freeze Procedure

1. Review this document without querying any v0.1.3 external source.
2. Compute its exact byte size and SHA-256.
3. Append a v0.1.3 entry to `pre_registration/FROZEN.md`.
4. Commit only this document, the v0.1.2 pilot failure record, and `FROZEN.md` as `Pre-registration v0.1.3 FROZEN`.
5. Verify the committed file reproduces the recorded digest.
6. Only then begin implementation and deterministic reacquisition from cursor zero.

---

## 18. Canonical Logical Query Templates

Templates are UTF-8, LF-only, with one final LF and no trailing spaces. Substitution is typed token replacement, never string formatting from remote/user text. The rendered query artifact is authoritative and its SHA-256 is computed before transport.

### 18.1 Gaia joined page

`{REQUEST_ROWS}` is an integer in `[1,500]`; `{CURSOR_U64}` is an unsigned integer; `{L_MIN}`/`{L_MAX}` are one-decimal literals from the 12 registered intervals; `{LATITUDE_PREDICATE}` is exactly `gs.b > 20.0` or `gs.b < -20.0`.

```sql
SELECT TOP {REQUEST_ROWS}
  gs.source_id AS gaia_dr3_source_id,
  gs.ra,
  gs.dec,
  gs.l AS galactic_l,
  gs.b AS galactic_b,
  gs.parallax,
  gs.parallax_error,
  gs.parallax_over_error,
  gs.pmra,
  gs.pmdec,
  gs.ruwe,
  gs.astrometric_excess_noise,
  gs.astrometric_excess_noise_sig,
  gs.phot_g_mean_mag,
  gs.phot_bp_rp_excess_factor,
  gs.ipd_frac_multi_peak,
  gs.ipd_frac_odd_win,
  gs.duplicated_source,
  gs.non_single_star,
  gs.classprob_dsc_combmod_quasar AS qso_probability,
  gs.classprob_dsc_combmod_galaxy AS galaxy_probability,
  gs.teff_gspphot,
  gs.logg_gspphot,
  gs.distance_gspphot,
  gs.ag_gspphot,
  awbn.angular_distance AS wise_xm_angular_distance,
  awbn.number_of_neighbours AS wise_xm_n_neighbours,
  awbn.number_of_mates AS wise_xm_n_mates,
  awbn.xm_flag AS wise_xm_flag,
  aw.designation AS allwise_designation,
  aw.w1mpro,
  aw.w1mpro_error,
  (1.0857 / aw.w1mpro_error) AS w1snr,
  aw.w2mpro,
  aw.w2mpro_error,
  (1.0857 / aw.w2mpro_error) AS w2snr,
  aw.w3mpro,
  aw.w3mpro_error,
  (1.0857 / aw.w3mpro_error) AS w3snr,
  aw.w4mpro,
  aw.w4mpro_error,
  (1.0857 / aw.w4mpro_error) AS w4snr,
  aw.cc_flags AS allwise_cc_flags,
  aw.ext_flag AS allwise_ext_flg,
  tmbn.angular_distance AS tmass_xm_angular_distance,
  tm.designation AS tmass_designation,
  tm.j_m AS tmass_j_m,
  tm.j_msigcom AS tmass_j_msigcom,
  tm.h_m AS tmass_h_m,
  tm.h_msigcom AS tmass_h_msigcom,
  tm.ks_m AS tmass_ks_m,
  tm.ks_msigcom AS tmass_ks_msigcom
FROM gaiadr3.gaia_source AS gs
  LEFT JOIN gaiadr3.allwise_best_neighbour AS awbn ON gs.source_id = awbn.source_id
  LEFT JOIN gaiadr1.allwise_original_valid AS aw ON awbn.original_ext_source_id = aw.designation
  LEFT JOIN gaiadr3.tmass_psc_xsc_best_neighbour AS tmbn ON gs.source_id = tmbn.source_id
  LEFT JOIN gaiadr1.tmass_original_valid AS tm ON tmbn.original_ext_source_id = tm.designation
WHERE
  gs.parallax_over_error >= 5.0
  AND gs.parallax > 0
  AND gs.parallax >= 5.000000
  AND gs.parallax_error > 0
  AND gs.phot_g_mean_mag >= -10.0
  AND gs.phot_g_mean_mag <= 18.0
  AND gs.phot_bp_rp_excess_factor >= 0.0
  AND gs.phot_bp_rp_excess_factor <= 100.0
  AND gs.ruwe < 1.2
  AND gs.duplicated_source = 'false'
  AND gs.non_single_star = 0
  AND gs.classprob_dsc_combmod_galaxy < 0.1
  AND gs.classprob_dsc_combmod_quasar < 0.1
  AND ABS(gs.b) > 20.0
  AND awbn.angular_distance <= 1.5
  AND awbn.number_of_neighbours = 1
  AND awbn.number_of_mates = 0
  AND aw.designation IS NOT NULL
  AND aw.w1mpro IS NOT NULL
  AND aw.w2mpro IS NOT NULL
  AND aw.w3mpro IS NOT NULL
  AND aw.w1mpro_error > 0
  AND aw.w2mpro_error > 0
  AND aw.w3mpro_error > 0
  AND aw.w1mpro_error <= 0.217140
  AND aw.w2mpro_error <= 0.217140
  AND aw.w3mpro_error <= 0.361900
  AND (aw.cc_flags IS NULL OR aw.cc_flags = '0000')
  AND (aw.ext_flag IS NULL OR aw.ext_flag = 0)
  AND tmbn.angular_distance <= 1.5
  AND tm.designation IS NOT NULL
  AND tm.ks_m IS NOT NULL
  AND tm.ks_msigcom > 0
  AND gs.teff_gspphot >= 1.0
  AND gs.teff_gspphot <= 100000.0
  AND gs.source_id > {CURSOR_U64}
  AND gs.l >= {L_MIN}
  AND gs.l < {L_MAX}
  AND {LATITUDE_PREDICATE}
ORDER BY gs.source_id
```

Endpoint: `https://gea.esac.esa.int/tap-server/tap`. The logical TAP operation is asynchronous; protocol-generated `/async` job URLs must remain same-origin under that endpoint and are not catalog redirects.

### 18.2 SIMBAD exclusion query

The TAP upload name is exactly `targets` with ordered schema `(gaia_dr3_source_id int64 non-null, ra float64 non-null, dec float64 non-null)`. It is a contiguous at-most-500-row slice of BP/RP parent order.

```sql
SELECT t.gaia_dr3_source_id AS gaia_dr3_source_id, b.main_id AS matched_object_id, o.otype AS matched_otype, b.ra AS matched_ra, b.dec AS matched_dec, DISTANCE(POINT('ICRS', t.ra, t.dec), POINT('ICRS', b.ra, b.dec)) * 3600.0 AS server_angular_distance_arcsec FROM TAP_UPLOAD.targets AS t JOIN basic AS b ON 1 = CONTAINS(POINT('ICRS', b.ra, b.dec), CIRCLE('ICRS', t.ra, t.dec, 0.008361111111111111)) JOIN otypes AS o ON b.oid = o.oidref WHERE o.otype IN ('AGN', 'Ae*', 'BLL', 'Bla', 'HH', 'LIN', 'Or*', 'QSO', 'Sy1', 'Sy2', 'SyG', 'TT*', 'Y*O', 'out', 'rG') ORDER BY gaia_dr3_source_id, server_angular_distance_arcsec, matched_object_id, matched_otype
```

Endpoint: `https://simbad.cds.unistra.fr/simbad/sim-tap`; asynchronous TAP; `maxrec=50001`. There are exactly `ceil(|B|/500)` logical SIMBAD requests.

### 18.3 Chen catalog request

VizieR is not treated as ADQL. Its canonical logical descriptor is exactly:

```text
Vizier:J/ApJS/211/25/catalog:columns=_RA,_DE,Name:row_limit=10000
```

Endpoint: `https://vizier.cds.unistra.fr/viz-bin/votable`. There is exactly one logical Chen request. Any library-generated parameter order is separately stored in the transport record; the descriptor above is the scientific request identity.

---

## 19. Ordered Table Schemas

Primitive types are Arrow logical types: `int64`, `float64`, `bool`, `string`, `timestamp[us,UTC]`. “NN” means non-null; “N” means nullable. A nullable numeric value is represented by a null bitmap, never a NaN payload. Strings are NFC-normalized valid UTF-8 without NUL. All tables reject unknown, missing, duplicate, or reordered columns.

### 19.1 Gaia decoded raw page, normalized page, and raw candidates

All three use this exact order. Raw decoded W4 columns are nullable independently only at the untrusted boundary; the normalized page and `raw_candidates` require the W4 triple all-null or all-present. Other nullability is identical.

| # | Column | Type/null | Domain |
|---:|---|---|---|
| 1 | `gaia_dr3_source_id` | int64 NN | `1..2^63-1`; unique in page/parent |
| 2–5 | `ra`, `dec`, `galactic_l`, `galactic_b` | float64 NN | `[0,360)`, `[-90,90]`, cell interval, hemisphere respectively |
| 6–8 | `parallax`, `parallax_error`, `parallax_over_error` | float64 NN | parallax `>=5`; error `>0`; ratio `>=5`; finite |
| 9–10 | `pmra`, `pmdec` | float64 N | finite when present |
| 11 | `ruwe` | float64 NN | `[0,1.2)` |
| 12–13 | `astrometric_excess_noise`, `astrometric_excess_noise_sig` | float64 N | finite and `>=0` when present |
| 14 | `phot_g_mean_mag` | float64 NN | `[-10,18]` |
| 15 | `phot_bp_rp_excess_factor` | float64 NN | `[0,100]` |
| 16–17 | `ipd_frac_multi_peak`, `ipd_frac_odd_win` | float64 N | `[0,100]` when present |
| 18 | `duplicated_source` | bool NN | false |
| 19 | `non_single_star` | int64 NN | 0 |
| 20–21 | `qso_probability`, `galaxy_probability` | float64 NN | `[0,0.1)` |
| 22 | `teff_gspphot` | float64 NN | `[1,100000]` K |
| 23 | `logg_gspphot` | float64 N | `[-10,20]` when present |
| 24 | `distance_gspphot` | float64 N | `>0` and `<=1e7` when present; not independent of parallax |
| 25 | `ag_gspphot` | float64 N | `[-10,100]` when present |
| 26 | `wise_xm_angular_distance` | float64 NN | `[0,1.5]` arcsec |
| 27–29 | `wise_xm_n_neighbours`, `wise_xm_n_mates`, `wise_xm_flag` | int64 NN | exactly 1, exactly 0, and `[0,255]` |
| 30 | `allwise_designation` | string NN | 1–512 UTF-8 bytes |
| 31–39 | `w1mpro`, `w1mpro_error`, `w1snr`, `w2mpro`, `w2mpro_error`, `w2snr`, `w3mpro`, `w3mpro_error`, `w3snr` | float64 NN | finite; errors `>0`; SNR/error and thresholds per Section 4.2 |
| 40–42 | `w4mpro`, `w4mpro_error`, `w4snr` | float64 N | raw: each independently nullable but any present value validated; normalized: all-null or finite all-present, error `>0`, SNR `>=2` and consistent |
| 43 | `allwise_cc_flags` | string N | null or exactly `0000` (all four bands) |
| 44 | `allwise_ext_flg` | int64 N | null or 0 |
| 45 | `tmass_xm_angular_distance` | float64 NN | `[0,1.5]` arcsec |
| 46 | `tmass_designation` | string NN | 1–512 UTF-8 bytes |
| 47–50 | `tmass_j_m`, `tmass_j_msigcom`, `tmass_h_m`, `tmass_h_msigcom` | float64 N | J/H all-present or all-null pairs; finite; present errors `>0` |
| 51–52 | `tmass_ks_m`, `tmass_ks_msigcom` | float64 NN | finite; error `>0` |

Magnitude fields have defensive domain `[-100,100]`; magnitude uncertainties and SNR values have domain `(0,1e6]` when present. The SNR consistency tolerances are those in Section 4.2. The raw-candidate table is unique and ordered `(cell_ordinal, source_id)`; `cell_ordinal` is derivable from coordinates/plan and is not an extra column.

### 19.2 BP/RP survivors and final controls

They contain the 52 normalized parent columns above followed by:

| # | Column | Type/null | Domain |
|---:|---|---|---|
| 53 | `gmag_bin_lower` | float64 NN | exact multiple of 0.5 from Section 5 |
| 54 | `bp_rp_excess_bin_median` | float64 NN | `[0,100]` |
| 55 | `bp_rp_excess_delta` | float64 NN | exact stored binary64 value satisfies `abs(value) <= 0.1` |

`bp_rp_survivors` and `quiet_negative` share this schema. Each is source-ID unique and preserves canonical parent order.

### 19.3 External raw/normalized evidence

| Table | Ordered columns and types |
|---|---|
| SIMBAD upload | `gaia_dr3_source_id int64 NN`, `ra float64 NN`, `dec float64 NN` |
| SIMBAD decoded raw | `gaia_dr3_source_id int64 NN`, `matched_object_id string NN`, `matched_otype string NN`, `matched_ra float64 NN`, `matched_dec float64 NN`, `server_angular_distance_arcsec float64 NN` |
| SIMBAD normalized | the seven-column exclusion schema below |
| Chen decoded raw | `_RA float64 NN`, `_DE float64 NN`, `Name string NN`, `_raw_row_index int64 NN` |
| Chen normalized | the seven-column exclusion schema below |

SIMBAD IDs must be in the upload; object IDs/types are 1–512 bytes; type is in the frozen vocabulary; matched RA/Dec are finite in `[0,360)`/`[-90,90]`; server separation is finite in `[0,30.1]`; raw rows are fewer than 50,001 and at most 100 discovered matches per upload source. The server distance is never copied into the normalized schema: local `pharos_spherical_sep_arcsec_v1` recomputation must be finite and `<=30.0`. Chen decoded raw column order is exactly `_RA`, `_DE`, `Name`, `_raw_row_index`; RA/Dec use `[0,360)`/`[-90,90]`, `Name` is 1–512 bytes, raw index is contiguous from zero, and rows are fewer than 10,000. `_raw_row_index` is added immediately after decoding, before any reorder, and is part of raw semantic identity.

The exact normalized exclusion schema is:

| # | Column | Type/null | Domain |
|---:|---|---|---|
| 1 | `gaia_dr3_source_id` | int64 NN | member of BP/RP parent |
| 2 | `exclusion_catalog` | string NN | `SIMBAD` or `Chen2014` |
| 3 | `exclusion_class` | string NN | `YSO`, `AGN`, or `debris_disk` consistent with catalog/type |
| 4 | `matched_object_id` | string NN | 1–512 bytes |
| 5 | `matched_otype` | string NN | frozen SIMBAD type or `debris_disk` |
| 6 | `angular_distance_arcsec` | float64 NN | `[0,30]` |
| 7 | `catalog_release` | string NN | exact release label from manifest |

Final `exclusions` is stable-sorted by BP/RP parent rank, catalog order (`SIMBAD`, `Chen2014`), separation, matched-object UTF-8 bytes, then matched-type UTF-8 bytes, and has no exact duplicate tuple.

### 19.4 Logical request index

`request_index` has one row per logical catalog request in global order (120 Gaia, derived SIMBAD count, one Chen):

```text
attempt_id string NN
logical_request_id string NN
global_sequence int64 NN
service string NN                  # gaia|simbad|chen
service_sequence int64 NN
parent_kind string NN              # selection_cell|bp_rp_survivors|catalog_descriptor
parent_start int64 NN
parent_rows int64 NN
stratum_id string N
cursor_before int64 N
requested_rows int64 NN
query_path string NN
query_byte_sha256 string NN
input_path string N
input_byte_sha256 string N
input_semantic_sha256 string N
raw_response_path string NN
raw_response_byte_sha256 string NN
raw_response_semantic_sha256 string NN
raw_response_rows int64 NN
normalized_response_path string NN
normalized_response_byte_sha256 string NN
normalized_response_semantic_sha256 string NN
normalized_response_rows int64 NN
simbad_radius_rejected_rows int64 N
simbad_duplicate_rows_removed int64 N
normalization_id string NN
successful_transport_ordinal int64 NN
first_started_at timestamp[us,UTC] NN
completed_at timestamp[us,UTC] NN
```

IDs/paths are unique and bounded; hashes are 64 lowercase hex; sequences are contiguous from zero; parent ranges exactly partition the registered parent where applicable. Gaia `requested_rows = raw_rows = normalized_rows`; for SIMBAD the two SIMBAD-only fields are non-null nonnegative and `raw_response_rows - simbad_radius_rejected_rows - simbad_duplicate_rows_removed = normalized_response_rows`; for Gaia/Chen they are null. Chen `requested_rows` is 10,000 as the catalog ceiling, not an expected row count.

`transport_attempts` is child-keyed by `(attempt_id, logical_request_id, transport_ordinal)` and ordered by global logical sequence then ordinal:

```text
attempt_id string NN
logical_request_id string NN
transport_ordinal int64 NN          # contiguous, starts 1
phase string NN                     # submit|poll|fetch|sync
started_at timestamp[us,UTC] NN
finished_at timestamp[us,UTC] NN
outcome string NN                   # success|retryable_failure|fatal_failure
http_status int64 N                 # 100..599
expected_hostname string NN          # exact allow-listed DNS hostname
peer_ip string NN                    # canonical public IPv4/IPv6 literal
peer_port int64 NN                   # exactly 443
leaf_certificate_sha256 string NN    # lowercase hex64
tls_version string NN               # exactly TLSv1.3
redirect_count int64 NN             # exactly 0
wire_bytes int64 NN
decompressed_bytes int64 NN
wire_sha256 string NN
decompressed_sha256 string NN
error_code string N                 # fixed generic enum, never remote payload
```

`attempt_state.jsonl` is UTF-8 LF JSON Lines, one exact-key object per transition: `attempt_id string`, `event_sequence int`, `from_state string|null`, `to_state string`, `recorded_at_utc string`, `actor_role string`, `evidence_semantic_sha256 string`, `previous_event_sha256 string|null`. Sequences start zero and are contiguous; each event SHA-256 is over its canonical RFC 8785 JSON bytes and chains to the previous event. Unknown keys/states/transitions fail. The packaged raw/final state file ends at its respective candidate-complete state; later Git/registry trust states remain external.

### 19.5 Semantic hash framing

Semantic identity is SHA-256 over: ASCII schema version length/value; row count; for each column in registered order, UTF-8 name length/value and logical type; then each row in canonical table order. Int64 is signed eight-byte little-endian; float64 is IEEE-754 little-endian after mapping `-0.0` to `+0.0` and rejecting NaN/infinity; bool is `00`/`01`; strings are NFC UTF-8 prefixed by unsigned eight-byte length; timestamps are signed int64 UTC microseconds. Every cell begins with null marker `00` or present marker `01`; null has no value bytes. Lengths are unsigned eight-byte little-endian. The semantic-hash algorithm ID is `pharos-semantic-frame-le-v1`.

Cross-runtime identity is the semantic hash, not Parquet byte equality. Release byte hashes still protect exact stored files and are exact registry fields. The only permitted Parquet profile is PyArrow 25.0.0, Parquet 2.6, `zstd` level 9, dictionary encoding off, statistics on, row-group target 50,000 (every full group exactly 50,000 and one final smaller group when needed), data page v2, no index, fixed registered metadata keys in UTF-8 bytewise order, and no writer timestamp. Rebuilds under the packaged toolchain must be byte-identical; other runtimes need only reproduce semantic hashes and cannot create a registered replacement release.

---

## 20. Manifest, Pass-Report, and Registry Schemas

All mappings use the exact key order shown, reject unknown/missing/duplicate/reordered keys, and use JSON-compatible scalar types in alias-free YAML. Strings are non-null unless explicitly marked nullable. `hex40` and `hex64` are lowercase ASCII hexadecimal of exact length; timestamps are RFC 3339 UTC with microseconds and terminal `Z`; paths obey Section 10; list order is semantic.

The ordered `ArtifactDescriptor` record is exactly: `path` string; `byte_sha256` hex64; `semantic_sha256` nullable hex64, null only for non-tabular text/binary artifacts; `bytes` int64 in `[0,2147483648]`; `rows` nullable int64, nonnegative only for tables; `schema_version` string 1–128 bytes; `columns` nullable ordered list of 1–64 unique strings, non-null only for tables; and `producer_role` enum `raw|release`. The ordered `ProducerRecord` is exactly: `git_commit` hex40; `source_tree_sha256` hex64; `uv_lock_sha256` hex64; `toolchain_sha256` hex64; and `source_distribution` `ArtifactDescriptor`.

The ordered `CatalogReleaseRecord` is exactly: `service` enum `gaia|allwise|tmass|simbad|chen`; `endpoint` one exact Section 18 HTTPS endpoint; `catalog_id` string 1–256 bytes; `release_id` string 1–128 bytes; `retrieved_at_utc` timestamp; and `query_template_byte_sha256` hex64. Checkpoint catalog records are exactly three in order `gaia, allwise, tmass`; final records are exactly five in order `gaia, allwise, tmass, simbad, chen`. Endpoint/catalog pairs are respectively `gaiadr3.gaia_source`, `gaiadr1.allwise_original_valid`, `gaiadr1.tmass_original_valid`, `basic+otypes`, and `J/ApJS/211/25/catalog`; no alias or substituted release is accepted.

The ordered `CheckpointCellRecord` is exactly: `id` registered cell string; `ordinal` int64 `[0,23]`; `longitude_min` float64; `longitude_max` float64; `hemisphere` enum `north|south`; `quota` int64 `2291|2292`; `cursor` positive int64; and `collected_rows` int64 equal to quota. The ordered `FinalCellRecord` is exactly the first six fields of `CheckpointCellRecord`, followed by `raw_rows` int64 equal to quota, `bp_rp_rows` int64 `[0,quota]`, `excluded_unique_sources` int64 `[0,bp_rp_rows]`, and `retained_rows` int64 equal to `bp_rp_rows-excluded_unique_sources`. `CheckpointSelectionRecord` is exactly: `strategy` = `24-cell-round-robin-keyset-v1`; `target_rows` = `55000`; `cell_order` list of the exact 24 IDs from Section 3; and `cells` list of 24 `CheckpointCellRecord` objects in ordinal order. `FinalSelectionRecord` has the same first three fields and a `cells` list of 24 `FinalCellRecord` objects.

The ordered `LimitsRecord` contains exactly these non-null int64 fields and values, in this order: `source_batch_rows=500`; `simbad_matches_per_source_catalog=100`; `simbad_maxrec=50001`; `chen_rows_exclusive_max=10000`; `cli_source_ids_max=10000`; `raw_candidate_rows_max=250000`; `final_control_rows_min=50000`; `final_control_rows_max=250000`; `exclusion_rows_max=5000000`; `wire_bytes_max=33554432`; `decompressed_response_bytes_max=67108864`; `deep_table_bytes_max=134217728`; `live_response_table_bytes_max=268435456`; `process_rss_bytes_max=1073741824`; `yaml_bytes_max=1048576`; `parquet_file_bytes_max=2147483648`; `parquet_footer_bytes_max=16777216`; `parquet_metadata_bytes_max=1048576`; `parquet_columns_max=64`; `parquet_row_groups_max=1024`; `parquet_nesting_depth_max=0`; `parquet_column_chunk_compressed_bytes_max=67108864`; `parquet_column_chunk_uncompressed_bytes_max=134217728`; `parquet_data_page_compressed_bytes_max=16777216`; `parquet_data_page_uncompressed_bytes_max=33554432`; `parquet_page_header_bytes_max=65536`; `parser_allocator_bytes_max=268435456`; `parser_address_space_bytes_max=1073741824`; `text_scalar_bytes_max=4096`; `catalog_text_bytes_max=512`; `query_bytes_max=65536`; `decoded_string_bytes_max=33554432`; `release_files_max=2048`; `release_tree_bytes_max=4294967296`; `relative_path_bytes_max=240`; `filename_component_bytes_max=180`; `logical_catalog_requests_max=231`; `tcp_connect_timeout_seconds=10`; `tls_handshake_timeout_seconds=10`; `response_header_timeout_seconds=60`; `body_read_timeout_seconds=600`; `gaia_logical_deadline_seconds=7200`; `gaia_poll_interval_seconds=10`; `gaia_poll_operations_max=720`; `simbad_logical_deadline_seconds=600`; `chen_logical_deadline_seconds=600`; `transport_attempts_max=3`; `retry_wait_1_seconds=5`; `retry_wait_2_seconds=15`; `redirects_max=0`; `peer_port=443`; and `ca_bundle_bytes=240216`. These are followed by non-null `tls_version` string exactly `TLSv1.3`, `ca_bundle_sha256` hex64 exactly `9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`, and `allowed_hostnames` list exactly `gea.esac.esa.int`, `simbad.cds.unistra.fr`, `vizier.cds.unistra.fr` in that order. Missing, extra, reordered, wrongly typed, or unequal values fail.

The ordered `CheckpointArtifactMap` contains exactly these `ArtifactDescriptor` fields: `packaged_pre_registration`, `source_distribution`, `uv_lock`, `toolchain`, `normalizer_registry`, `ca_bundle`, `request_index`, `transport_attempts`, `request_evidence` (an ordered list of descriptors in logical-request order and within-request query/input/raw/normalized order), `raw_candidates`, and `attempt_state`. The `ca_bundle` descriptor must have path ending in the registered digest, `bytes=240216`, and the registered byte SHA-256. The ordered `FinalArtifactMap` contains those same fields in that order followed by `bp_rp_survivors`, `exclusions`, `quiet_negative`, and `pass_report`. Every regular file in the candidate tree except its manifest appears exactly once either as a direct descriptor or inside `request_evidence`; descriptor order must match the tree contract.

### 20.1 Gaia checkpoint manifest

```text
schema_version: string = pharos.quiet-negative-checkpoint-manifest.v0.1.3
status: string = candidate
attempt_id: UUIDv4
state: string = gaia_candidate_complete
pre_registration_path: string
pre_registration_byte_sha256: hex64
pre_registration_bytes: int64 > 0
created_at_utc: timestamp
raw_producer: ProducerRecord
catalog_releases: list[CatalogReleaseRecord], exactly 3
selection: CheckpointSelectionRecord
gaia_logical_requests: int64 = 120
transport_attempt_count: int64 >= 120
artifacts: CheckpointArtifactMap
request_order_rows_semantic_sha256: hex64
canonical_parent_rows_semantic_sha256: hex64
limits: LimitsRecord
```

Counts require target/raw rows 55,000, 24 complete quotas, 120 logical requests, and request-index/transport relationships. `status` never changes in place.

### 20.2 Final candidate manifest

```text
schema_version: string = pharos.quiet-negative-manifest.v0.1.3
status: string = candidate
attempt_id: UUIDv4
state: string = final_candidate_complete
pre_registration_path: string
pre_registration_byte_sha256: hex64
pre_registration_bytes: int64 > 0
created_at_utc: timestamp
raw_checkpoint_manifest_path: string
raw_checkpoint_manifest_byte_sha256: hex64
raw_checkpoint_registry_entry_id: string 1..128 bytes
raw_checkpoint_candidate_commit: hex40
raw_checkpoint_review_evidence_commit: hex40
raw_producer: ProducerRecord
release_producer: ProducerRecord
catalog_releases: list[CatalogReleaseRecord], exactly 5
selection: FinalSelectionRecord
gaia_logical_requests: int64 = 120
simbad_logical_requests: int64 = ceil(bp_rp_rows/500)
chen_logical_requests: int64 = 1
total_logical_requests: int64 = preceding sum
transport_attempt_count: int64 >= total_logical_requests
raw_rows: int64 = 55000
bp_rp_rows: int64 in [50000,55000]
simbad_raw_rows: int64 in [0,5000000]
simbad_normalized_rows: int64 in [0,simbad_raw_rows]
simbad_unique_sources: int64 in [0,bp_rp_rows]
chen_raw_rows: int64 in [0,9999]
chen_normalized_rows: int64 in [0,5000000]
chen_unique_sources: int64 in [0,bp_rp_rows]
exclusion_rows: int64 = simbad_normalized_rows + chen_normalized_rows
excluded_unique_sources: int64 in [0,bp_rp_rows]
final_rows: int64 = bp_rp_rows - excluded_unique_sources
artifacts: FinalArtifactMap
request_order_rows_semantic_sha256: hex64
canonical_parent_rows_semantic_sha256: hex64
bp_rp_rows_semantic_sha256: hex64
exclusions_semantic_sha256: hex64
final_rows_semantic_sha256: hex64
bp_rp_algorithm_id: string = bp-rp-derive-v013
simbad_normalization_id: string = simbad-local-exclusion-v013
chen_match_id: string = chen-local-exclusion-v013
final_difference_id: string = final-difference-v013
limits: LimitsRecord
```

Manifest relationships are those in Section 9 plus `gaia_logical=120`, `simbad_logical=ceil(bp_rp_rows/500)`, `chen_logical=1`, and total sum. The manifest has no `manifest_sha256`, `registered`, or registry digest field: a manifest cannot self-bind or self-authorize.

### 20.3 Pass report

```text
schema_version: string = pharos.quiet-negative-pass-report.v0.1.3
attempt_id: UUIDv4
pre_registration_sha256: hex64
raw_checkpoint_manifest_sha256: hex64
generated_at_utc: timestamp
producer: ProducerRecord
gates: list[GateRecord], exactly 12 in gate_id order 01..12
all_passed: bool
test_results: list[TestResultRecord], exactly 7 in registered order
no_model_fit_attestation: NoModelFitRecord
```

`GateRecord` is exactly: `gate_id` enum `01` through `12`; `passed` bool; `evidence_paths` ordered non-empty list of strings; `evidence_sha256` same-length ordered list of hex64; and `summary` string 1–512 bytes. `TestResultRecord` is exactly: `test_id` enum `pytest|ruff|mypy|build|dependency_audit|fuzz_smoke|artifact_verify`; `command` string 1–4096 bytes; `exit_code` int64 exactly 0; `stdout_sha256` hex64; `stderr_sha256` hex64; `started_at_utc` timestamp; and `finished_at_utc` timestamp not earlier than start. Registered test order is the enum order shown. `NoModelFitRecord` is exactly: `passed` bool exactly true; `scanned_paths` ordered non-empty list of repository-relative strings; `scan_tool` string 1–128 bytes; and `evidence_sha256` hex64. `all_passed` equals logical AND of exactly 12 unique gates and all test exit codes. The pass report cannot confer registry trust.

### 20.4 Review attestation

Each review attestation is alias-free strict YAML at exact path `pre_registration/reviews/v0.1.3/<attempt_id>.<review_role>.yaml`, where `review_role` is `raw_checkpoint` or `final_release`. It has exactly these ordered keys:

```text
schema_version: string = pharos.control-review-attestation.v0.1.3
review_role: enum raw_checkpoint|final_release
attempt_id: UUIDv4
candidate_commit: hex40
candidate_manifest_path: exact repository-relative candidate manifest path
candidate_manifest_byte_sha256: hex64
pre_registration_byte_sha256: hex64
reviewer_identity: string 1..128 bytes
reviewer_signing_key_sha256: hex64
reviewed_at_utc: timestamp
artifact_identities: list[RegistryArtifactIdentity], non-empty and complete
checks: list[ReviewCheckRecord], non-empty and role-complete
outcome: string = approved
notes: string 0..2048 bytes
```

`RegistryArtifactIdentity` is exactly: `path` string; `byte_sha256` hex64; `semantic_sha256` nullable hex64 under the same rule as `ArtifactDescriptor`; `bytes` nonnegative int64; `rows` nullable nonnegative int64; `schema_version` string; and `columns` nullable ordered list of strings. `ReviewCheckRecord` is exactly: `check_id` enum `tree|manifest|schemas|counts|queries|transport|resources|reconstruction|tests|no_model_fit`; `passed` bool exactly true; `evidence_path` string; `evidence_sha256` hex64; and `summary` string 1–512 bytes. Raw review contains `tree,manifest,schemas,counts,queries,transport,resources,reconstruction` in that order; final review contains all ten in enum order. `reviewer_signing_key_sha256` is SHA-256 over the decoded OpenSSH public-key blob used by Git's SSH signature verifier and must appear in the pre-existing authorized-reviewer tuple below. The review commit contains only this new attestation, is SSH-signed by the declared key, and has the candidate commit as its direct first parent. The attestation does not contain or predict its own review commit hash.

### 20.5 External registry

The only trust registry path is `src/pharos/trusted_control_releases_v013.py`; it is code-reviewed source, not an artifact supplied by a release. It exports immutable tuples whose entries have exact schema:

```text
entry_id: unique string 1..128 bytes
role: enum raw_checkpoint|final_release
attempt_id: UUIDv4
candidate_commit: hex40
manifest_path: exact repository-relative path
manifest_byte_sha256: hex64
pre_registration_byte_sha256: hex64
producer: ProducerRecord
raw_checkpoint_entry_id: nullable string; null iff raw_checkpoint
artifact_identities: ordered tuple[RegistryArtifactIdentity], complete
request_index_byte_sha256: hex64
request_index_semantic_sha256: hex64
transport_attempts_byte_sha256: hex64
transport_attempts_semantic_sha256: hex64
pass_report_byte_sha256: nullable hex64; null iff raw_checkpoint
review_attestation_path: exact repository-relative path
review_attestation_byte_sha256: hex64
review_evidence_commit: hex40
registry_parent_commit: hex40
```

The registry module exports exactly three immutable tuples named `AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256`, `TRUSTED_RAW_CHECKPOINTS`, and `TRUSTED_FINAL_RELEASES`. The first contains unique hex64 decoded-OpenSSH-key-blob hashes established in the implementation commit before acquisition; candidate/review/registry commits may not change it. Every trusted element is one exact ordered entry above and unknown tuple fields, extra module data, mutable containers, duplicate IDs, or role/list mismatch fail loader import. For `raw_checkpoint`, final-only fields are null; for `final_release`, `raw_checkpoint_entry_id` and pass report are non-null and refer to an earlier raw entry. `review_evidence_commit` must already contain the byte-identical immutable attestation, be a verified SSH-signed direct child of `candidate_commit`, and equal `registry_parent_commit`; the registry-only commit is its direct child. No entry contains or predicts the hash of the commit that contains itself. The loader imports only this exact module, matches every field, verifies ancestry/signatures/diffs, and opens files through contained no-follow descriptors. The acquisition/release workers cannot write this path. A registrar may add one tuple entry only; CI rejects any change to the authorized-key tuple, any existing entry, or any other file. The reviewer supplies the verified candidate commit/hash set, the registrar transcribes it, and a second reviewer approves the registry diff. Registry compromise is a trust-root compromise and is never masked as ordinary data validation.

---

## 21. Expanded Roles, Privileges, and Escalation Analysis

| Role | Network | Reads | Writes | Forbidden |
|---|---|---|---|---|
| Gaia acquisition worker | Gaia allow-listed host only | frozen prereg, packaged code/lock, own attempt | mode-0700 Gaia quarantine | BP/RP/external/model/registry writes |
| Release/external worker | SIMBAD and VizieR allow-listed hosts only | exact registered Gaia checkpoint, frozen package | new final candidate staging | Gaia query, registry/model writes |
| Artifact reviewer | none | immutable candidate commit/tree, source package, existing registry | one signed review attestation commit outside candidate | candidate or registry mutation |
| Registrar | none | signed approved review-evidence commit and candidate commit | exact registry module only | artifact generation, network, manifest/review-attestation mutation |
| Downstream loader | none | registered release and registry | none | review mode, network, repair/coercion |

Workers run as dedicated OS users/containers with no shared writable directories, no ptrace/process-inspection capability, no Docker socket, no SSH agent, no cloud metadata access, read-only source/lock/prereg mounts, a bounded writable attempt mount, and default-deny egress. Registrar credentials are absent from worker environments. Secrets are outside the repository, scope-limited, and opened only by descriptor; logs contain aggregate IDs/counts, never payloads or credentials.

Escalation paths and containment are explicit:

- **malicious remote row -> parser execution/resource exhaustion:** flat strict schemas, no object deserialization, pre-decompression limits, bounded strings/rows/memory, fuzzed normalizers;
- **remote URL/redirect -> credential exfiltration/SSRF:** fixed TLS1.3 hosts, zero redirects, no proxies, public-IP rejection, no credential forwarding;
- **artifact path -> host filesystem:** relative allow-listed paths, no-follow descriptor opens, symlink/hard-link/inode checks, separate UID, no-replace publication;
- **compromised dependency -> forged data or host access:** exact lock/toolchain/source package, minimal egress, unprivileged isolated worker, raw-response review and offline reconstruction; dependency compromise can invalidate an attempt but cannot write the registry;
- **same-UID attacker -> TOCTOU/process tampering:** same-UID sharing is prohibited for trust-separated roles; attempts use dedicated UID/container, mode 0700, ptrace denial, immutable/read-only inputs, open-descriptor hashing, and final source/lock rehash. If same-UID isolation cannot be demonstrated, the attempt fails;
- **worker compromise -> trusted release:** candidate status has no trust; a signed review-evidence commit and its direct-child registry-only commit are both required;
- **registry modification -> arbitrary trust:** exact-path CI diff restriction, registrar-only privilege, independent review, immutable Git history, and exact manifest/artifact identities. A malicious registrar plus approving reviewer is outside containment and is disclosed as total trust-root compromise.

Availability attacks fail the attempt or leave a quarantined manifestless/candidate directory. They never relax selection, accept partial data, reuse another attempt, or promote an unregistered release.

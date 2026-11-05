# Pre-Registration Freeze Record

This file records the cryptographic state of each frozen pre-registration document at the moment of freeze. Once a document is recorded here, no further edits to that file are permitted; supersedence is the only allowed change path (a new file at a higher version number).

The SHA-256 below is the hash of the document file at the byte level. Re-computing `shasum -a 256` over the named file at any later time MUST return this exact hash. A mismatch invalidates the freeze for that file.

---

## v0.1 — IR / Astrometric Confounder Benchmark

| Field | Value |
|---|---|
| Document | [`v0.1_ir_benchmark.md`](v0.1_ir_benchmark.md) |
| Date frozen | 2026-05-11 |
| Status | FROZEN (with cosmetic corrigendum, see below) |
| Superseded by | (none) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---|---|
| Initial freeze | 2026-05-11 | 10,457 bytes | `0784859d8cad230d98a43c14e84862396855f590586dd72b29c7e2676963d38c` |
| Cosmetic corrigendum | 2026-05-12 | 10,494 bytes | `ff35549f2ebbb5befd48e07248918fc608992dae54529adc118371249afa0202` |

### Corrigendum (2026-05-12)

GitHub's GFM table renderer breaks on `|` characters inside table-cell code spans, even when those pipes are inside backticks. The §5 `P_lowgalb` row contained `|b|` (Galactic-latitude absolute value), which rendered as a broken table cell. **No scoring rule, threshold, β weight, or pass criterion was changed.** The expression was rewritten to use the equivalent `abs(b)` notation so the table renders correctly. The semantic meaning is identical:

> Before: `1` if `|b| < 10°` else `max(0, (20 - |b|) / 10)`
> After:  `1` if `abs(b) < 10°` else `max(0, (20 - abs(b)) / 10)`

The git diff between the initial-freeze commit and the corrigendum commit is the byte-level proof that this is purely a typesetting fix. The integrity of the freeze rests on `git log -p -- pre_registration/v0.1_ir_benchmark.md`, which shows every change.

### Verification command

```sh
shasum -a 256 pre_registration/v0.1_ir_benchmark.md
```

Expected output (current state):

```
ff35549f2ebbb5befd48e07248918fc608992dae54529adc118371249afa0202  pre_registration/v0.1_ir_benchmark.md
```

---

## v0.1.1 — Calibrated β + X-ray HOT DOG

| Field | Value |
|---|---|
| Document | [`v0.1.1_calibrated_betas_and_xray_hot_dog.md`](v0.1.1_calibrated_betas_and_xray_hot_dog.md) |
| Date frozen | 2026-05-12 |
| Status | FROZEN |
| Supersedes | v0.1 §5 (confounder vector) only |
| Superseded by | v0.1.2 |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---|---|
| Initial freeze | 2026-05-12 | 10,828 bytes | `d9ad5d0fecbed29a77cbecc78a9bf238ef500dbc40fba342f4b52de5c9e95a89` |

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md
```

Expected output:

```
d9ad5d0fecbed29a77cbecc78a9bf238ef500dbc40fba342f4b52de5c9e95a89  pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md
```

---

## v0.1.2 — Subtype-Aware Confounders + X-ray Evidence

| Field | Value |
|---|---|
| Document | [`v0.1.2_subtype_confounders_and_xray_evidence.md`](v0.1.2_subtype_confounders_and_xray_evidence.md) |
| Date frozen | 2026-08-05 |
| Status | FROZEN |
| Supersedes | v0.1.1 in full; v0.1 remains the base release |
| Superseded by | (none) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-08-05 | 19,123 bytes | `68e4f2d3359a5c4f208426d80a56f58788bdea6003e07ae0a75dc68cbcc259eb` |

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md
```

Expected output:

```text
68e4f2d3359a5c4f208426d80a56f58788bdea6003e07ae0a75dc68cbcc259eb  pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md
```

---

## v0.1.3 — Hardened Quiet-Negative Control Population

| Field | Value |
|---|---|
| Document | [`v0.1.3_control_population.md`](v0.1.3_control_population.md) |
| Date frozen | 2026-08-06 |
| Status | FROZEN |
| Supersedes | v0.1 Section 6 quiet-negative population acquisition procedure and v0.1.2 implementation assumptions for that procedure only |
| Superseded by | v0.1.4 (enumerated provisions only) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-08-06 | 87,851 bytes | `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43` |

### Supporting disposition record

The observed v0.1.2 hardened control-population pilot did not ship and is not an input to v0.1.3. Its immutable non-release record is preserved for audit:

| Field | Value |
|---|---|
| Document | [`failed_attempts/v0.1.2_hardened_control_population.md`](failed_attempts/v0.1.2_hardened_control_population.md) |
| Date recorded | 2026-08-06 |
| Status | DID NOT SHIP — quarantined; prohibited from model fitting, scoring, calibration, inference, release use, or v0.1.3 reuse |
| File size | 15,481 bytes |
| SHA-256 | `a6e32d509e31c3e346e79a81eb70b56d7d5310872624480742081b1387853256` |

### Verification commands

```sh
shasum -a 256 pre_registration/v0.1.3_control_population.md
shasum -a 256 pre_registration/failed_attempts/v0.1.2_hardened_control_population.md
```

Expected output:

```text
b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43  pre_registration/v0.1.3_control_population.md
a6e32d509e31c3e346e79a81eb70b56d7d5310872624480742081b1387853256  pre_registration/failed_attempts/v0.1.2_hardened_control_population.md
```

---

## v0.1.4 — Control-Population Protocol Repair

| Field | Value |
|---|---|
| Document | [`v0.1.4_control_population.md`](v0.1.4_control_population.md) |
| Date frozen | 2026-11-05 |
| Status | FROZEN |
| Supersedes | the enumerated provisions of v0.1.3 listed in its Section 5 only; all other v0.1.3 provisions are incorporated by reference (effective protocol = v0.1.3 as amended) |
| Superseded by | (none) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-11-05 | 17,714 bytes | `ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b` |

### Scope note

v0.1.4 repairs protocol executability only: the producer-provenance record schema (raw producer bound by registered-checkpoint reference; release producer carries the single embedded source distribution), the authorized-reviewer signing-key trust root (pinned in the frozen document), and the dependency/CA toolchain identity (certifi 2026.10.18, CA bundle 234,072 bytes, SHA-256 `d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453`). No population, quota, gate, query, exclusion, threshold, or pass criterion changed. Every v0.1.4 release tree packages both frozen documents. The reviewer trust root currently designates the operator; review is not independent of the operator until a further supersession adds an independent key.

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.4_control_population.md
```

Expected output:

```text
ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b  pre_registration/v0.1.4_control_population.md
```

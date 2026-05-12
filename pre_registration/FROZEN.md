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
| Superseded by | (none) |

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

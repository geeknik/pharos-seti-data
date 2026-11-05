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
| Superseded by | v0.1.5 (release-platform identity only) |

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

---

## v0.1.5 — Release-Platform Identity Repair

| Field | Value |
|---|---|
| Document | [`v0.1.5_platform_repair.md`](v0.1.5_platform_repair.md) |
| Date frozen | 2026-11-05 |
| Status | FROZEN |
| Supersedes | the release-platform identity values registered through v0.1.4 Section 5.3 only (CPython 3.14.6 / macOS 27.0 / build 26A5388g / kernel 27.0.0 / OpenSSL 3.6.3) |
| Superseded by | v0.1.6 (transport TLS policy only) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-11-05 | 5,925 bytes | `7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d` |

### Scope note

Platform re-registration only: CPython 3.14.10 / macOS 27.3 (build 26C5035r) / kernel 27.3.0 / OpenSSL 4.1.0 (23 Oct 2026), measured on the acquisition host 2026-11-05. No scientific rule, schema, dependency, or trust-root change. Candidate trees package all three frozen documents (v0.1.5 primary; v0.1.4 and v0.1.3 incorporated).

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.5_platform_repair.md
```

Expected output:

```text
7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d  pre_registration/v0.1.5_platform_repair.md
```

---

## v0.1.6 — Transport TLS Policy Repair

| Field | Value |
|---|---|
| Document | [`v0.1.6_tls_policy_repair.md`](v0.1.6_tls_policy_repair.md) |
| Date frozen | 2026-11-05 |
| Status | FROZEN |
| Supersedes | the transport TLS policy provisions of the effective protocol only (TLS 1.3 mandatory; evidence and limits fields pinned to TLSv1.3) |
| Superseded by | v0.1.7 (parser containment only) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-11-05 | 5,679 bytes | `54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650` |

### Supporting disposition record

The first v0.1.5-registered Gaia attempt failed closed before any request
completed: the registered endpoint refused all OpenSSL TLS 1.3 handshakes
(alert 40) while completing TLS 1.2 ECDHE-AES-GCM under the same CA validation.
Its immutable record is preserved for audit:

| Field | Value |
|---|---|
| Document | [`failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md`](failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md) |
| Date recorded | 2026-11-05 |
| Status | FAILED BEFORE ANY REQUEST — no data acquired; nothing reusable |
| File size | 2,370 bytes |
| SHA-256 | `5f4e96eefda12aea3b8ab4e1fefdaafe007dbbb3e533cf145ac3f89f86d28c6c` |

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.6_tls_policy_repair.md pre_registration/failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md
```

Expected output:

```text
54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650  pre_registration/v0.1.6_tls_policy_repair.md
5f4e96eefda12aea3b8ab4e1fefdaafe007dbbb3e533cf145ac3f89f86d28c6c  pre_registration/failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md
```

---

## v0.1.7 — Parser Containment Repair

| Field | Value |
|---|---|
| Document | [`v0.1.7_parser_containment_repair.md`](v0.1.7_parser_containment_repair.md) |
| Date frozen | 2026-11-05 |
| Status | FROZEN |
| Supersedes | the parser-worker address-space sentence of the effective protocol only (hard RLIMIT_AS 1 GiB, fatal if unenforceable) |
| Superseded by | (none) |

### Freeze record

| Stage | Date | File size | SHA-256 |
|---|---|---:|---|
| Initial freeze | 2026-11-05 | 4,454 bytes | `62f1b74efd85fb6f36203094c27a947bf2a16e77c0b5ee428a749e55142aeb49` |

### Supporting disposition record

The first v0.1.6 attempt completed the entire first transport chain (submit,
poll, job document, 236,436-byte VOTable result) and then failed closed in the
decode worker: macOS 27.3 refuses any finite RLIMIT_AS, making the inherited
equality check unenforceable on the registered platform. Its immutable record:

| Field | Value |
|---|---|
| Document | [`failed_attempts/v0.1.6_parser_address_space_unenforceable.md`](failed_attempts/v0.1.6_parser_address_space_unenforceable.md) |
| Date recorded | 2026-11-05 |
| Status | FAILED AFTER TRANSPORT, BEFORE DECODE — no data entered derivation |
| File size | 1,760 bytes |
| SHA-256 | `880fb3344bd64fb6df8575e9474039b9996ff3b07426587fb08743238390d8ae` |

### Verification command

```sh
shasum -a 256 pre_registration/v0.1.7_parser_containment_repair.md pre_registration/failed_attempts/v0.1.6_parser_address_space_unenforceable.md
```

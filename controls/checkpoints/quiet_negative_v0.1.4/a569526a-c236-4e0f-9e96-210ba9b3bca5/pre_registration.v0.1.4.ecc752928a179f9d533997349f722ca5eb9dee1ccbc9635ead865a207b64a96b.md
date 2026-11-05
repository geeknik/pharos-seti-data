# Pre-Registration: Pharos v0.1.4 — Control-Population Protocol Repair

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** repair of the frozen v0.1.3 control-population protocol's producer-provenance schema, reviewer trust root, and dependency-toolchain identity; all other v0.1.3 provisions are incorporated unchanged by reference

**Supersedes:** only the enumerated provisions of [`v0.1.3_control_population.md`](v0.1.3_control_population.md) listed in Section 5 of this document; v0.1.3 is incorporated by reference for everything else

**Incorporated document:** `v0.1.3_control_population.md`, 87,851 bytes, SHA-256 `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43` (FROZEN 2026-08-06)

**Design inputs:** frozen v0.1.3 bytes; [`FROZEN.md`](FROZEN.md); [`failed_attempts/v0.1.2_hardened_control_population.md`](failed_attempts/v0.1.2_hardened_control_population.md); [`docs/v0.1.3-experimental-scaffold.md`](../docs/v0.1.3-experimental-scaffold.md); the 2026-11-04 `pip-audit` result of the locked environment (17 findings, security input only); and the operator-designated reviewer public key recorded in Section 5.2. No catalog query, pilot row, quarantined artifact, model output, or threshold observation informed this document.

This document becomes immutable only after its exact byte SHA-256 and size are appended to [`FROZEN.md`](FROZEN.md) and the freeze-recorded state is committed per Section 8. No v0.1.4 query, acquisition, checkpoint creation, exclusion request, model fit, or pass-criterion evaluation may occur before that freeze commit. After freeze, correction is by a versioned superseding pre-registration, never by editing this file.

---

## 1. Claim Boundary

Unchanged from v0.1.3 Section 1. v0.1.4 will produce, at most, one validated quiet-negative control release for the WISE-only coverage class under the v0.1.3 scientific rules as amended here. This document repairs protocol executability; it does not change any population, quota, gate, query, exclusion rule, threshold, or pass criterion. It fits no model, estimates no coefficient, and makes no technosignature claim. The v0.1.2 quarantine and the v0.1.3 blocked state remain historical facts; nothing from either is an input.

## 2. Effective Protocol

The effective v0.1.4 protocol is **v0.1.3 as amended by Section 5 of this document**. Where this document is silent, the incorporated v0.1.3 provision governs verbatim. Where Section 5 replaces a provision, the replacement text governs and the v0.1.3 text is void for v0.1.4 execution only (the frozen v0.1.3 bytes remain the historical record of the v0.1.3 registration). Ambiguity between the two documents fails closed and requires a recorded clarification before acquisition, not an implementation choice.

Every v0.1.4 release tree packages byte-identical copies of **both** frozen documents (Section 5.5), so the effective protocol is offline-reconstructible from the release alone (v0.1.3 Section 8.2).

## 3. Registered Paths

Per `docs/scientific_standards.md` Section 2.2, v0.1.4 names its paths before execution:

```text
raw checkpoint quarantine:  controls/checkpoints/quiet_negative_v0.1.4/<attempt_id>/
final candidate quarantine: controls/quiet_negative_v0.1.4/<attempt_id>/
review attestations:        pre_registration/reviews/v0.1.4/<attempt_id>.<review_role>.yaml
trust registry module:      src/pharos/trusted_control_releases_v014.py
analysis ledger:            analysis_ledger/v0.1.4/<attempt_id>.toml
normalizer module:          src/pharos/control_population_v014.py
```

There is no generic fallback path. The analysis ledger follows the `pharos.analysis-ledger.v1` schema of the scientific standards and is created before execution; the in-artifact `attempt_state.jsonl` machine of v0.1.3 Section 13 governs acquisition state and is not replaced by the ledger.

## 4. Blockers Repaired

`status.toml` records three v0.1.3 blockers. This document repairs exactly them:

1. **Producer-provenance schema contradiction** — v0.1.3 Sections 11.1 and 20 require the final manifest to record **two** `ProducerRecord` values, each containing a `source_distribution` `ArtifactDescriptor`, while v0.1.3 Section 16 and the `FinalArtifactMap` provide exactly **one** embedded source distribution. Two distinct producer identities cannot both be proven from one distribution slot, and Section 11.1 forbids inferring either from the other. Repaired by Section 5.1.
2. **Empty authorized-reviewer trust root** — v0.1.3 left `AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256` to be established no later than the implementation commit; it was never established. Repaired by pinning the trust root inside this frozen document (Section 5.2).
3. **Failing locked dependency audit** — v0.1.3 freezes the vulnerable certifi 2026.07.22 identity into its toolchain and CA contracts while requiring a passing dependency audit. Repaired by registering the remediated identities (Section 5.3) and requiring a zero-finding audit at gate time.

## 5. Amendments to the Incorporated v0.1.3 Provisions

Each amendment names the amended v0.1.3 provision and supplies the replacement. All other v0.1.3 provisions are unchanged.

### 5.1 Producer provenance (amends v0.1.3 Sections 11.1, 16, 20, 20.2)

The producers remain separate, independently recorded, and neither may be inferred from the other (v0.1.3 Section 11.1, unchanged). The record types change:

**`ReleaseProducerRecord`** (ordered; replaces `ProducerRecord` wherever a producer with an embedded distribution is recorded):

```text
git_commit hex40
source_tree_sha256 hex64
uv_lock_sha256 hex64
toolchain_sha256 hex64
source_distribution ArtifactDescriptor
```

**`RawProducerReference`** (ordered; used for the raw producer in the final manifest only):

```text
git_commit hex40
source_tree_sha256 hex64
uv_lock_sha256 hex64
toolchain_sha256 hex64
raw_checkpoint_registry_entry_id string 1..128 bytes
raw_checkpoint_manifest_path exact repository-relative path
raw_checkpoint_manifest_byte_sha256 hex64
```

`RawProducerReference` has **no** `source_distribution` field. The raw producer's source distribution is not re-embedded in the final tree; it is preserved exactly once, inside the registered raw checkpoint tree whose own manifest carries the raw producer's full `ReleaseProducerRecord`-typed record with its embedded distribution (v0.1.3 Section 20.1 structure, unchanged for the checkpoint).

Amended contracts:

- **Final manifest (v0.1.3 Section 20.2):** `raw_producer: RawProducerReference`; `release_producer: ReleaseProducerRecord`. All other fields and relationships unchanged.
- **Final tree `software/` (v0.1.3 Section 16):** contains exactly the **release producer's** source distribution (`pharos-seti-data-v0.1.4-source.<sha256>.tar`), its `uv.lock`, `toolchain`, `normalizer_registry`, and `ca_bundle`. The single distribution slot is satisfied by exactly the one producer that produced the final tree.
- **`FinalArtifactMap` (v0.1.3 Section 20):** the `source_distribution` slot binds the release producer's tar; add an `incorporated_pre_registration` slot immediately after `packaged_pre_registration` (Section 5.5). `CheckpointArtifactMap` is unchanged except for Section 5.5 and the version-string rule of Section 5.4.
- **Loader cross-check (new required validation):** the final-manifest `RawProducerReference` must equal, field-for-field over `git_commit`, `source_tree_sha256`, `uv_lock_sha256`, and `toolchain_sha256`, the raw-producer record inside the registered raw checkpoint manifest bound by `raw_checkpoint_manifest_byte_sha256`; the referenced registry entry must exist with role `raw_checkpoint` and bind that same manifest hash. Any mismatch fails closed.

Offline reconstruction (v0.1.3 Section 8.2) is preserved: the raw producer's code is loadable and verifiable from the registered checkpoint tree; the release producer's code from the final tree; neither record is derivable from the other.

### 5.2 Authorized-reviewer trust root (amends v0.1.3 Section 20.5)

`AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256` is pinned by this document as exactly one entry:

```text
119b9e83dd61e470b8fa52c2269403b45958a7cfaca7a26e2142478a44fb9f07
```

This is SHA-256 over the decoded OpenSSH public-key blob of the operator-designated reviewer key (ssh-ed25519, `ssh-keygen -lf` fingerprint `SHA256:EZueg91h5HC4+lLCJpQDtFlYp8+sp6JuIUJHikT7nwc`, designated 2026-11-05). The v0.1.4 implementation commit must define `src/pharos/trusted_control_releases_v014.py` to export `AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256` as an immutable tuple containing exactly this one value. No later commit in the v0.1.4 workflow may add, remove, or reorder trust-root entries; doing so requires a new superseding pre-registration. Review attestations (v0.1.3 Section 20.4 structure, unchanged) must be SSH-signed by exactly this key and must record its hash in `reviewer_signing_key_sha256`.

Until a future supersession adds an independent second reviewer, the reviewer role and the operator are the same person; every surface presenting a v0.1.4 release must disclose that the review was not independent of the operator.

### 5.3 Dependency and toolchain identity (amends v0.1.3 Sections 6.2 platform sentence, 10 network policy, 15 gate 11, 16 trees/toolchain, 20 LimitsRecord and CheckpointArtifactMap)

The locked-environment audit of 2026-11-04 found 17 advisories in four packages. v0.1.4 registers this remediation:

| Package | Vulnerable | Advisory IDs | Registered fix |
|---|---|---|---|
| certifi | 2026.7.22 | PYSEC-2026-4320 | **2026.10.18** |
| urllib3 | 2.7.0 | PYSEC-2026-4175, PYSEC-2026-4176, PYSEC-2026-4177 | **2.8.0** |
| filelock | 3.32.2 | GHSA-v4x8-3wr5-3wq8, GHSA-9vhv-jxww-xfm5, GHSA-567q-5qvw-pf92, GHSA-m462-7rxw-wvpg, GHSA-j8f7-rjxc-mr56, GHSA-8mx5-7m5m-r77g, GHSA-69hj-f68j-2879, GHSA-9c4x-gm8v-wgc4, GHSA-rfpc-qcw5-3pc4, GHSA-cwqr-hh33-gh44, GHSA-fq56-3cx3-fjxp, GHSA-6627-m3xw-93mp | **4.2.1** (satisfies the 4.0.9 minimum of GHSA-j8f7-rjxc-mr56 and every 4.2.1-listed fix) |
| msgpack | 1.2.1 | GHSA-j586-36cw-2gc2 | **1.2.3** |

Replacement values, wherever v0.1.3 pins the CA identity (its Section 10 network-policy sentence, Section 16 `ca_bundle` filename in both trees, Section 16 `toolchain.yaml` fields, Section 20 `LimitsRecord`, and the `ca_bundle` descriptor rule):

```text
certifi_version    = 2026.10.18
ca_bundle_bytes    = 234072
ca_bundle_sha256   = d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453
ca_bundle filename = ca_bundle.d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453.pem
```

The 234,072-byte size and digest are measured over `cacert.pem` as packaged in certifi 2026.10.18. Every other `toolchain.yaml` field of v0.1.3 Section 16 is unchanged (CPython 3.14.6, uv 0.11.12, macOS 27.0 / 26A5388g / arm64, OpenSSL 3.6.3, pandas 3.0.5, pyarrow 25.0.0, numpy 2.5.1, pyyaml 6.0.3, astropy 8.0.1, astroquery 0.4.11). urllib3, filelock, and msgpack are transitive lock identities, not `toolchain.yaml` fields; their remediation is registered in the table above and enforced by the amended gate:

**Amended gate 11 (v0.1.3 Section 15):** the `dependency_audit` test result must record exit code 0 with **zero** findings under the remediated lock. The remediated `uv.lock` is committed adjacent to this document's freeze commit; every v0.1.4 producer records the `uv_lock_sha256` of its own clean tree, which necessarily differs from any v0.1.3-era lock hash.

### 5.4 Version strings and identifiers (amends every v0.1.3 occurrence)

For v0.1.4 execution, the following renames apply mechanically and exhaustively; each renamed identifier has otherwise identical semantics:

- Every schema identifier `pharos.*.v0.1.3` becomes `pharos.*.v0.1.4` (all sixteen identifiers of v0.1.3 Section 9.1, plus the checkpoint-manifest, final-manifest, pass-report, and review-attestation schema strings of Section 20).
- `parquet_writer_profile` becomes `pharos-parquet-v014` (v0.1.3 Section 19.5).
- Tree roots, review paths, registry module, ledger, and normalizer module per Section 3.
- Packaged preregistration filename `pre_registration.v0.1.4.<sha256>.md`, where `<sha256>` is this document's frozen digest.
- Source archives are named `pharos-seti-data-v0.1.4-source.<sha256>.tar`.
- The five normalizer-registry tuples of v0.1.3 Section 16 become: `(0, gaia-page-normalize-v014, src/pharos/control_population_v014.py, normalize_gaia_page, pharos.gaia-decoded-page.v0.1.4, pharos.gaia-normalized-page.v0.1.4)`; `(1, bp-rp-derive-v014, src/pharos/control_population_v014.py, derive_bp_rp_survivors, pharos.quiet-negative-raw.v0.1.4, pharos.quiet-negative-bp-rp.v0.1.4)`; `(2, simbad-local-exclusion-v014, src/pharos/control_population_v014.py, normalize_simbad_exclusions, pharos.simbad-decoded-raw.v0.1.4, pharos.quiet-negative-exclusions.v0.1.4)`; `(3, chen-local-exclusion-v014, src/pharos/control_population_v014.py, match_chen_exclusions, pharos.chen-decoded-raw.v0.1.4, pharos.quiet-negative-exclusions.v0.1.4)`; `(4, final-difference-v014, src/pharos/control_population_v014.py, derive_quiet_negative, pharos.quiet-negative-bp-rp.v0.1.4, pharos.quiet-negative.v0.1.4)`.
- The manifest algorithm/normalization identifiers of v0.1.3 Section 20.2 become `bp-rp-derive-v014`, `simbad-local-exclusion-v014`, `chen-local-exclusion-v014`, and `final-difference-v014`.

### 5.5 Packaged pre-registration pair (amends v0.1.3 Section 12)

Every v0.1.4 candidate tree (checkpoint and final) contains, at its root, byte-identical packaged copies of **both**:

```text
pre_registration.v0.1.4.<this document's frozen sha256>.md
pre_registration.v0.1.3.b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43.md
```

Both manifests add one ordered field pair after `pre_registration_bytes`: `incorporated_pre_registration_path` (exact relative tree path of the packaged v0.1.3 copy) and `incorporated_pre_registration_byte_sha256` (exactly `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`). Both artifact maps add the `incorporated_pre_registration` descriptor immediately after `packaged_pre_registration`. Every Parquet file embeds the v0.1.4 digest as `pharos.pre_registration_sha256`; loaders verify both packaged copies against the recorded digests and, when a repository checkout is present, against `pre_registration/FROZEN.md`.

## 6. Explicit Non-Amendments

Unchanged and governing verbatim from v0.1.3: Sections 1 (claim boundary), 2 (threat model, except the CA values of Section 5.3 here), 3 (parent population, 24 cells, exact 55,000 quota allocation, deterministic selection), 4 (all eligibility gates including the optional-W4 rule), 5 (BP/RP derivation), 6 (external exclusions, endpoints, radii, vocabularies, and the registered spherical function, except the platform-sentence toolchain values), 7 (minimum size and stratifiability), 8 (per-request evidence, provenance, reconstructibility), 9 (relational invariants), 10 (all resource, input, filesystem, publication, retry, and network bounds, except the CA identity), 11.2 (the ten-step registry workflow, except path/module renames), 13 (freeze policy and state machine), 14 (required controls and tests), 15 (pass/fail gates, except amended gate 11), 17 (superseded by this document's own Section 8 for v0.1.4's freeze), 18 (all canonical query templates and endpoints), 19 (all ordered table schemas and semantic hashing), 20.1 (checkpoint manifest structure), 20.3 (pass report), 20.4 (review attestation structure), 20.5 (registry entry schema and CI diff restriction, modulo the module rename and Section 5.2), and 21 (roles and escalation analysis).

## 7. Pilot and Quarantine Non-Use

No v0.1.2 quarantined row, cursor, response table, checkpoint, median, exclusion, or derived artifact is an input to this document or to any v0.1.4 execution. The v0.1.3 experimental scaffold informed no scientific rule here; its recorded engineering observations (frozen-schema contradiction, empty trust root, unrecorded build/audit gates) are protocol-executability facts, not scientific results. Acquisition under v0.1.4, when separately authorized, starts from cursor zero under a new `attempt_id`.

## 8. Freeze Procedure for This Document

1. Review this document without querying any external catalog source and without creating any v0.1.4 artifact.
2. Compute its exact byte size and SHA-256.
3. Append a v0.1.4 entry to `pre_registration/FROZEN.md`, and set the v0.1.3 entry's `Superseded by` field to `v0.1.4 (enumerated provisions only)`.
4. In one freeze commit, commit only: this document; the updated `FROZEN.md`; the updated `tests/test_governance.py` pins (this document's inventory entry, the new `FROZEN.md` digest, the `status.toml` v0.1.4 record, the remediated dependency-audit state, and an inventory rule permitting only `pre_registration/reviews/v0.1.4/` attestations matching the registered naming pattern as additional files); and the operator-edited `status.toml` recording v0.1.4 as frozen with implementation not started and acquisition prohibited.
5. In one adjacent lock-remediation commit, update `uv.lock` to the four registered fix versions of Section 5.3 and record the remediated `scientific_state_commit`; `uv lock --check`, the full test suite, and `uv run pip-audit` (zero findings) must pass from a clean tree of the remediated lock.
6. Verify the committed document reproduces the recorded digest; publish under the operator's push authorization.
7. Implementation and reacquisition remain prohibited until separately authorized in `status.toml`; the reviewer designated in Section 5.2 cannot be added, removed, or changed without a further supersession.

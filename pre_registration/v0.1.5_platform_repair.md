# Pre-Registration: Pharos v0.1.5 — Release-Platform Identity Repair

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** re-registration of the exact release-platform identity for the v0.1.4 control-population protocol; no scientific rule, schema, path, dependency, or trust-root change

**Supersedes:** only the release-platform identity values registered through v0.1.4 Section 5.3 (inheriting v0.1.3 Section 16 `toolchain.yaml` values and the Section 6.2 platform sentence); the effective protocol otherwise remains v0.1.3 as amended by v0.1.4

**Incorporated documents:** `v0.1.4_control_population.md` (17,714 bytes, SHA-256 `ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b`, FROZEN 2026-11-05) and, through it, `v0.1.3_control_population.md` (87,851 bytes, SHA-256 `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`, FROZEN 2026-08-06)

**Design inputs:** the runtime platform measurements below, taken 2026-11-05 on the acquisition host (Homebrew CPython, uv 0.11.12); the frozen v0.1.4/v0.1.3 registrations; and the locked dependency environment. No catalog query, pilot artifact, threshold, or scientific observation informed this document.

This document becomes immutable after its byte SHA-256 and size are appended to [`FROZEN.md`](FROZEN.md) and committed. No v0.1.5 acquisition may occur before that freeze commit.

---

## 1. Blocker Repaired

The v0.1.4-effective toolchain contract (v0.1.3 Section 16 as amended) registers the release platform as CPython 3.14.6 on macOS 27.0 (build 26A5388g, kernel 27.0.0) with OpenSSL 3.6.3. The acquisition host no longer provides that platform: its current, measured state is CPython 3.14.10 on macOS 27.3 (build 26C5035r, kernel 27.3.0) with OpenSSL 4.1.0 (23 Oct 2026). A registered checkpoint cannot be produced under the superseded identity, and silently accepting a drifted runtime would violate the frozen fail-closed platform check. This document re-registers the measured platform prospectively. Nothing else changes.

## 2. Amendments

### 2.1 Registered `toolchain.yaml` values (amends the v0.1.4-effective Section 16 contract)

| Field | Superseded value | Registered value |
|---|---|---|
| `python_version` | 3.14.6 | **3.14.10** |
| `openssl_version` | OpenSSL 3.6.3 9 Jun 2026 | **OpenSSL 4.1.0 23 Oct 2026** |
| `os_version` | 27.0 | **27.3** |
| `os_build` | 26A5388g | **26C5035r** |
| `kernel_release` | 27.0.0 | **27.3.0** |
| `uv_version` | 0.11.12 | 0.11.12 (unchanged; measured present) |

Every other `toolchain.yaml` field is unchanged: CPython; macOS; arm64; the measured `libc_math_runtime_identity`/dyld shared-cache fields (recorded at runtime, never pinned); pandas 3.0.5; pyarrow 25.0.0; numpy 2.5.1; pyyaml 6.0.3; astropy 8.0.1; astroquery 0.4.11; certifi 2026.10.18; CA bundle 234,072 bytes, SHA-256 `d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453`; Parquet 2.6; profile `pharos-parquet-v014`. The registered scientific stack was verified importable and version-exact under the registered platform on 2026-11-05.

### 2.2 Packaged pre-registration set (amends v0.1.4 Section 5.5)

Every candidate tree packages byte-identical copies of all three frozen documents:

```text
pre_registration.v0.1.5.<this document's frozen sha256>.md
pre_registration.v0.1.4.ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b.md
pre_registration.v0.1.3.b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43.md
```

Both manifests replace the single incorporated-document field pair with an ordered `incorporated_pre_registrations` list of exactly two entries — v0.1.4 then v0.1.3 — each with exact relative path and byte SHA-256. Both artifact maps list both incorporated descriptors immediately after `packaged_pre_registration`. `pharos.pre_registration_sha256` in every Parquet file, the request index, manifests, and pass report is the v0.1.5 digest.

### 2.3 Identifiers, verification, and freeze ancestry

No table, manifest, attestation, or registry schema changes: the v0.1.4-registered schema identifiers, module names (`control_population_v014.py`, `trusted_control_releases_v014.py`), normalizer tuples, tree roots, review paths, and the `pharos.*.v0.1.4` strings remain exactly as registered by v0.1.4 Section 5.4. The frozen-registration verification binds this document's bytes and requires producer HEAD to descend from the v0.1.5 freeze commit (which itself descends from the v0.1.4 freeze commit `07ca855920cb2209d7f9c78794fa85671e2793d3`).

## 3. Explicit Non-Amendments

Unchanged and governing verbatim: every scientific provision of v0.1.3 as amended by v0.1.4 (populations, quotas, gates, queries, exclusions, bounds, evidence, invariants, workflow, roles); the v0.1.4 producer-provenance records and loader cross-check; the pinned reviewer trust root (operator-designated ssh-ed25519, blob SHA-256 `119b9e83dd61e470b8fa52c2269403b45958a7cfaca7a26e2142478a44fb9f07`; review remains non-independent of the operator); the dependency remediation and zero-finding audit gate; and the quarantine non-use rule.

## 4. Freeze Procedure

1. Review without querying any external catalog source.
2. Compute this document's exact byte size and SHA-256.
3. Append a v0.1.5 entry to `pre_registration/FROZEN.md`; set the v0.1.4 entry's `Superseded by` to `v0.1.5 (release-platform identity only)`.
4. One freeze commit: this document, updated `FROZEN.md`, updated `tests/test_governance.py` pins (including the new `FROZEN.md` digest and `status.toml` v0.1.5 record), and the operator-edited `status.toml`.
5. One implementation commit: update the registered platform constants and the three-document packaging in the `*_v014` modules with all tests passing from a clean tree.
6. Verify the committed digest; publish under the operator's push authorization. Acquisition remains prohibited until separately authorized in `status.toml`.

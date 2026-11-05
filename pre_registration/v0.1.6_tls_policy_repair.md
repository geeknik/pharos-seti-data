# Pre-Registration: Pharos v0.1.6 — Transport TLS Policy Repair

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** re-registration of the transport TLS version policy for the v0.1.4 control-population protocol; no scientific rule, population, quota, gate, query, dependency, platform, or trust-root change

**Supersedes:** only the TLS policy provisions of the effective protocol (v0.1.3 Section 10 sentence "TLS 1.3 with SNI, hostname validation, and certificate validation is mandatory", the transport-evidence field `tls_version` pinned to exactly `TLSv1.3`, and the `LimitsRecord.tls_version` entry, as carried unchanged through v0.1.4 and v0.1.5)

**Incorporated documents:** `v0.1.5_platform_repair.md` (5,925 bytes, SHA-256 `7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d`, FROZEN 2026-11-05), `v0.1.4_control_population.md` (17,714 bytes, SHA-256 `ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b`, FROZEN 2026-11-05), and `v0.1.3_control_population.md` (87,851 bytes, SHA-256 `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`, FROZEN 2026-08-06)

**Design inputs:** the registered failure record
[`failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md`](failed_attempts/v0.1.5_gaia_tls13_endpoint_refusal.md)
(attempt `cade7ae9-fb90-4dc3-99b5-dfb41eb408fb`, failed 2026-11-05 before any
request completed) and the handshake evidence it preserves. No catalog content,
pilot artifact, threshold, or scientific observation informed this document.

This document becomes immutable after its byte SHA-256 and size are appended to
[`FROZEN.md`](FROZEN.md) and committed.

---

## 1. Blocker Repaired

The effective protocol requires exactly TLS 1.3 to every registered endpoint. The
registered Gaia endpoint (`gea.esac.esa.int:443`) returned `handshake_failure`
(alert 40) to TLS 1.3 ClientHellos from every OpenSSL-based client tested on the
acquisition host (OpenSSL 4.1.0 and 3.x via CPython, and the OpenSSL CLI), while
completing TLS 1.2 with ECDHE-RSA-AES128-GCM-SHA256 under the same registered
CA validation. A TLS-1.3-only client therefore cannot currently acquire from the
registered archive at all. This document registers a TLS 1.2 floor / TLS 1.3
ceiling, AEAD-only policy: TLS 1.3 remains required-preferred and is used whenever
the server completes it; TLS 1.2 is permitted only with forward-secret ECDHE and
AES-GCM suites. Everything else in the transport trust model is unchanged.

## 2. Amendments

### 2.1 TLS policy (amends the effective Section 10 transport policy)

- Minimum version: TLS 1.2. Maximum version: TLS 1.3. TLS 1.3 is offered first and
  must be used whenever the server selects it.
- Permitted suites: all TLS 1.3 AEAD suites; for TLS 1.2 exactly
  `ECDHE-ECDSA-AES256-GCM-SHA384`, `ECDHE-ECDSA-AES128-GCM-SHA256`,
  `ECDHE-RSA-AES256-GCM-SHA384`, `ECDHE-RSA-AES128-GCM-SHA256`. No CBC mode, no
  static-RSA key exchange, no SHA-1, no RC4, no NULL suites, and no session
  renegotiation.
- Unchanged and still mandatory: SNI with the allow-listed hostname; certificate
  validation against the registered certifi 2026.10.18 bundle (234,072 bytes,
  SHA-256 `d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453`);
  anonymous credentials; zero redirects; public-peer validation; no proxies,
  netrc, ambient CA overrides, or client certificates.

### 2.2 Transport evidence (amends the effective Section 19.4/20 fields)

`transport_attempts.tls_version` records the **negotiated** version and is an
enum over exactly `TLSv1.3` and `TLSv1.2`; any other value fails. The
`LimitsRecord` entries `tls_version_min = "TLSv1.2"` and
`tls_version_max = "TLSv1.3"` replace the single `tls_version` entry, in that
order. Review checks and every other field are unchanged.

### 2.3 Packaged pre-registration set (amends v0.1.5 Section 2.2)

Every candidate tree packages byte-identical copies of all four frozen documents
(v0.1.6 primary; incorporated v0.1.5, v0.1.4, v0.1.3, in that order). The
manifest `incorporated_pre_registrations` list has exactly three entries with
exact paths and byte SHA-256s. Freeze verification binds this document and
requires ancestry from its freeze commit (which descends from `824935dabac415fad5375862e3a1048485369545`).

## 3. Explicit Non-Amendments

Unchanged and governing verbatim: every scientific provision of v0.1.3 as amended
by v0.1.4 and v0.1.5; the release-platform identity (CPython 3.14.10 / macOS 27.3 /
kernel 27.3.0 / OpenSSL 4.1.0); the producer-provenance records; the reviewer
trust root (blob SHA-256 `119b9e83dd61e470b8fa52c2269403b45958a7cfaca7a26e2142478a44fb9f07`;
review remains non-independent of the operator); the dependency registration and
zero-finding audit gate; endpoints, DNS/peer policy, byte bounds, retry policy,
and the quarantine non-use rule.

## 4. Freeze Procedure

1. Review without querying any external catalog source.
2. Compute this document's exact byte size and SHA-256.
3. Append a v0.1.6 entry to `pre_registration/FROZEN.md`; set the v0.1.5 entry's
   `Superseded by` to `v0.1.6 (transport TLS policy only)`.
4. One freeze commit: this document, the failed-attempt record, updated
   `FROZEN.md`, updated `tests/test_governance.py` pins, and the operator-edited
   `status.toml` v0.1.6 record.
5. One implementation commit: registered TLS context (1.2 floor / 1.3 ceiling,
   AEAD-only), negotiated-version evidence, four-document packaging, and limits
   fields, with all tests passing from a clean tree.
6. Verify the committed digest; publish under the operator's push authorization.
   Acquisition remains prohibited until separately authorized in `status.toml`.

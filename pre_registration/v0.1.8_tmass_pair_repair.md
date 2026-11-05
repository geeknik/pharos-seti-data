# Pre-Registration: Pharos v0.1.8 — 2MASS Pair Ingestion Repair

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** amendment of the 2MASS J/H magnitude–uncertainty pair rule for the v0.1.4 control-population protocol; no other scientific rule, schema, path, dependency, platform, TLS policy, containment mechanism, or trust-root change

**Supersedes:** only the second paragraph of v0.1.3 Section 4.4 (v0.1.3 lines 176–177: "For each of J and H, magnitude and uncertainty are an all-present or all-null pair. A partial pair, nonnumeric value, infinity, NaN represented as a value rather than null, or nonpositive present uncertainty fails.") as carried unchanged through v0.1.4–v0.1.7

**Incorporated documents:** v0.1.7 (4,454 bytes, `62f1b74efd85fb6f36203094c27a947bf2a16e77c0b5ee428a749e55142aeb49`), v0.1.6 (5,679 bytes, `54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650`), v0.1.5 (5,925 bytes, `7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d`), v0.1.4 (17,714 bytes, `ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b`), v0.1.3 (87,851 bytes, `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`)

**Design inputs:** the registered failure record
[`failed_attempts/v0.1.8_tmass_partial_pairs.md`](failed_attempts/v0.1.8_tmass_partial_pairs.md)
(attempt `b20e4cbc-3346-4d37-8510-706b547521de`, failed 2026-11-05 at logical
request 10 of 120 after 5,500 successfully validated rows), plus the full-schema
audit preserved there: across those rows, the only registered-schema violation in
the entire archive response is the J/H partial-pair pattern. No threshold,
quota, exclusion, or pass criterion was consulted.

---

## 1. Blocker Repaired

The effective protocol requires every 2MASS J and H magnitude–uncertainty pair to
be all-present or all-null, failing any partial pair. The real Gaia DR3 archive
returns, at a low rate, rows whose 2MASS magnitude is present while its
uncertainty is null (the catalog itself omits the uncertainty). Under the frozen
rule every acquisition attempt eventually meets such a row and fails closed; the
protocol is therefore unexecutable against the registered archive. This document
extends to the J/H pairs the same canonical-missingness rule the protocol already
registers for the optional W4 triple (v0.1.3 Section 4.3), preserving fail-closed
treatment for every other malformation.

## 2. Amendment

The superseded sentence is replaced by:

> For each of J and H, magnitude and uncertainty form one pair. A pair that is
> fully present must be finite with a strictly positive uncertainty and magnitude
> in `[-100, 100]`. A pair with a present magnitude and a null uncertainty — the
> archive's recorded-magnitude-without-quoted-uncertainty case — is canonically
> represented as two nulls at ingestion, exactly as the W4 triple rule of Section
> 4.3 canonicalizes its well-formed partial triples. A pair with a null magnitude
> and a present uncertainty, a nonnumeric or infinite value, NaN represented as a
> value rather than null, or a nonpositive present uncertainty fails. Persisted
> artifacts must already use the canonical all-present or all-null
> representation; loaders do not repair them.

The frozen Gaia query template (v0.1.3 Section 18.1) is unchanged: rows are
selected exactly as registered; the amendment affects only their canonical
ingestion representation. The Ks magnitude/uncertainty rule (always present,
finite, positive uncertainty) is unchanged.

## 3. Explicit Non-Amendments

Unchanged and governing verbatim: every other provision of v0.1.3 as amended
through v0.1.7 — populations, quotas, the W4 rule, all other gates, queries,
exclusions, bounds, evidence, producer provenance, platform, TLS policy, parser
containment, the reviewer trust root, and the quarantine non-use rule (the
failed attempt's pages, including its 5,500 validated rows, remain prohibited
inputs). Candidate trees package all six frozen documents; manifests list the
five incorporated predecessors in order.

## 4. Freeze Procedure

1. Review without querying any external catalog source.
2. Compute this document's exact byte size and SHA-256.
3. Append a v0.1.8 entry to `pre_registration/FROZEN.md`; set the v0.1.7 entry's
   `Superseded by` to `v0.1.8 (2MASS pair ingestion only)`.
4. One freeze commit: this document, the failed-attempt record, updated
   `FROZEN.md`, updated `tests/test_governance.py` pins, and the operator-edited
   `status.toml` v0.1.8 record.
5. One implementation commit: J/H canonical-missingness in page normalization
   with adversarial tests, six-document packaging, with all tests passing from a
   clean tree.
6. Verify the committed digest; publish under the operator's push authorization.
   Acquisition remains prohibited until separately authorized in `status.toml`,
   and any new attempt starts from cursor zero under a new attempt id.

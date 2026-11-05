# Pre-Registration: Pharos v0.1.7 — Parser Containment Repair

**Status:** PROSPECTIVE DRAFT — MUST BE FROZEN BEFORE ACQUISITION

**Scope:** amendment of the parser-worker containment mechanism for the v0.1.4 control-population protocol; no scientific rule, schema value, path, dependency, platform, TLS policy, or trust-root change

**Supersedes:** only the parser-worker address-space sentence of the effective protocol (v0.1.3 Section 10: the parser worker's hard `RLIMIT_AS` of exactly 1,073,741,824 bytes whose inability to establish and read back is fatal), as carried unchanged through v0.1.4, v0.1.5, and v0.1.6

**Incorporated documents:** `v0.1.6_tls_policy_repair.md` (5,679 bytes, SHA-256 `54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650`), `v0.1.5_platform_repair.md` (5,925 bytes, SHA-256 `7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d`), `v0.1.4_control_population.md` (17,714 bytes, SHA-256 `ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b`), and `v0.1.3_control_population.md` (87,851 bytes, SHA-256 `b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43`)

**Design inputs:** the registered failure record
[`failed_attempts/v0.1.6_parser_address_space_unenforceable.md`](failed_attempts/v0.1.6_parser_address_space_unenforceable.md)
(attempt `12e076f2-e894-4a67-a8b8-eab992763431`, failed 2026-11-05 after a fully
successful first transport chain). No catalog content entered derivation; no
threshold or scientific observation informed this document.

---

## 1. Blocker Repaired

The effective protocol makes an exact 1 GiB hard `RLIMIT_AS` a fatal-if-unenforceable
parser precondition. The registered operating system (macOS 27.3) refuses to lower
`RLIMIT_AS` to any finite value — `EINVAL` even in a bare interpreter whose mapped
footprint is ~17 MB — so every decode worker fails closed and no page can be parsed.
This document amends the containment mechanism: the address-space limit becomes a
best-effort platform defense applied when the platform accepts it and recorded when
it does not, while the mandatory containment is the already-registered bounded
parser allocator and byte caps, which are unaffected by this operating-system
behavior.

## 2. Amendment

The parser-worker sentence is replaced in full by:

> Every table parser runs in a fresh isolated worker. Before any table-library
> import or use, the worker applies a hard `RLIMIT_AS` of 1,073,741,824 bytes when
> — and only when — the platform accepts it, and records the outcome in the
> attempt evidence; refusal by the platform is not fatal. Independently and
> mandatorily, the worker enforces the registered bounded parser allocator
> (268,435,456 bytes of live allocations, refusing any allocation beyond it), the
> 33,554,432-byte wire cap, the 67,108,864-byte decompressed cap, and every
> registered table-shape cap; violating any mandatory bound fails the attempt.
> Failure to apply either class of bound when the platform supports it remains
> fatal.

All `LimitsRecord` values are unchanged, including `parser_address_space_bytes_max`
(now the best-effort target) and `parser_allocator_bytes_max` (mandatory). The
`process_rss_bytes_max` bound is unchanged and mandatory whenever the platform
enforces or reports it.

## 3. Explicit Non-Amendments

Unchanged and governing verbatim: every scientific provision of v0.1.3 as amended
through v0.1.6; the release platform; the TLS policy; producer provenance; the
reviewer trust root; dependencies; and the quarantine non-use rule. Candidate
trees package all five frozen documents; manifests list the four incorporated
predecessors in order.

## 4. Freeze Procedure

1. Review without querying any external catalog source.
2. Compute this document's exact byte size and SHA-256.
3. Append a v0.1.7 entry to `pre_registration/FROZEN.md`; set the v0.1.6 entry's
   `Superseded by` to `v0.1.7 (parser containment only)`.
4. One freeze commit: this document, the failed-attempt record, updated `FROZEN.md`,
   updated `tests/test_governance.py` pins, and the operator-edited `status.toml`
   v0.1.7 record.
5. One implementation commit: best-effort address-space application with recorded
   outcome, mandatory allocator and byte caps unchanged, five-document packaging.
6. Verify the committed digest; publish under the operator's push authorization.
   Acquisition remains prohibited until separately authorized in `status.toml`.

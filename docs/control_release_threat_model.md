# Quiet-Negative Control Acquisition and Release Threat Model

**Recorded:** 2026-08-05, before the hardened acquisition/release implementation
was evaluated. This document describes implementation controls; it does not
change the frozen scientific selection or scoring rules.

## Assets and trust boundaries

The protected assets are the frozen pre-registration, selected source
identities, exclusion decisions, artifact bytes, provenance, dependency lock,
and any optional archive credential. Remote TAP/VizieR/SIMBAD responses, cache
files, manifests, paths, and command-line values are untrusted. The relevant
boundaries are remote service to response validator, checkpoint to resume
loader, validated tables to release writer, and release manifest to downstream
loader. The acquisition process has network access but no need to execute
remote content; downstream loaders need only read access to a single contained
release directory.

## Principal attacks and containment

- **Selection bias or replay:** a source-ID cursor can concentrate a sample in
  one sky region, and an old checkpoint can silently replace a new plan.
  Acquisition therefore uses fixed sky strata, per-stratum cursors and quotas,
  and binds the complete selection plan into checkpoint and release provenance.
- **Schema or scientific-gate bypass:** a malicious or stale Parquet file may
  have plausible columns while violating Gaia, AllWISE, 2MASS, effective-
  temperature, BP/RP, exclusion, or uniqueness gates. Loaders re-run every
  registered gate and reject unknown columns, duplicate identifiers, residual
  duplicate exclusion identities, and relational count mismatches.
- **Resource exhaustion:** YAML aliases, very large manifests, Parquet metadata,
  or excessive row counts can consume memory before validation. File byte size
  and Parquet metadata row counts are bounded before materialization; network
  and retained-match limits remain fail-closed.
- **Path substitution:** symlinks or traversal can redirect reads/writes outside
  the release root. Paths must be relative, resolve inside the expected root,
  and contain no symlink at any existing component. Release files are regular,
  non-symlink files.
- **Partial or conflicting publication:** crashes or a repeated run can leave a
  mixed generation. Temporary files are flushed and fsynced, content-addressed
  payloads are installed with exclusive same-filesystem links, and directory
  metadata is fsynced before the manifest commit marker is linked and fsynced.
  An exclusive directory reservation prevents replacement races. A crash can
  leave a manifestless partial directory, which remains fail-closed and requires
  explicit operator cleanup; any existing target or manifest causes refusal.
- **Provenance substitution:** catalog labels alone do not bind what was queried.
  Each request records HTTPS endpoint, input/query hash, response hash, row
  count, and timestamps. The release also binds selection strata, repository
  commit, and `uv.lock` hash; manifest relationships are checked against the
  loaded tables.
- **Supply-chain drift:** all direct runtime and development dependencies are
  exactly pinned and the lock hash is part of release provenance.

No control in this design turns missing coverage into negative evidence, logs
credentials or payloads, follows release symlinks, overwrites a prior release,
or permits remote strings to become commands.

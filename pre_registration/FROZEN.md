# Pre-Registration Freeze Record

This file records the cryptographic state of each frozen pre-registration document at the moment of freeze. Once a document is recorded here, no further edits to that file are permitted; supersedence is the only allowed change path (a new file at a higher version number).

The SHA-256 below is the hash of the document file at the byte level. Re-computing `shasum -a 256` over the named file at any later time MUST return this exact hash. A mismatch invalidates the freeze for that file.

---

## v0.1 — IR / Astrometric Confounder Benchmark

| Field | Value |
|---|---|
| Document | [`v0.1_ir_benchmark.md`](v0.1_ir_benchmark.md) |
| Date frozen | 2026-05-11 |
| File size at freeze | 10,457 bytes |
| SHA-256 at freeze | `0784859d8cad230d98a43c14e84862396855f590586dd72b29c7e2676963d38c` |
| Capturing commit | Recorded by the same commit that creates this row. To verify, run `git log -1 --format='%H %ai' -- pre_registration/v0.1_ir_benchmark.md` from this repo. |
| Status | FROZEN |
| Superseded by | (none) |

### Verification command

```sh
shasum -a 256 pre_registration/v0.1_ir_benchmark.md
```

Expected output:

```
0784859d8cad230d98a43c14e84862396855f590586dd72b29c7e2676963d38c  pre_registration/v0.1_ir_benchmark.md
```

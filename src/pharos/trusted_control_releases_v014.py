"""External trust roots for Pharos v0.1.4 control releases.

The authorized reviewer signing key is pinned by the frozen v0.1.4
pre-registration (Section 5.2): SHA-256 over the decoded OpenSSH public-key
blob of the operator-designated ssh-ed25519 key.  No commit in the v0.1.4
workflow may add, remove, or reorder trust-root entries; doing so requires a
new superseding pre-registration.  Review is not independent of the operator
until a further supersession adds an independent key; every presenting
surface must disclose that.

No artifact is trusted yet: the checkpoint and final-release allow-lists
stay empty until the registered candidate -> review-evidence -> registry
commit sequence populates them under the frozen v0.1.4 workflow.
"""

AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256: tuple[str, ...] = (
    "119b9e83dd61e470b8fa52c2269403b45958a7cfaca7a26e2142478a44fb9f07",
)
TRUSTED_RAW_CHECKPOINTS: tuple[tuple[object, ...], ...] = ()
TRUSTED_FINAL_RELEASES: tuple[tuple[object, ...], ...] = ()

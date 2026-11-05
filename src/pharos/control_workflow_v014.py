"""Stateful orchestration for the frozen v0.1.4 acquisition and release phases.

Transport is intentionally injected by a dedicated worker.  This module never
opens a socket: it proves request order and ensures no scientific state advances
until a complete raw response has passed the frozen normalizer.
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from pharos import trusted_control_releases_v014 as trust
from pharos.control_artifacts_v014 import probe_rename_excl, sha256_file
from pharos.control_loaders_v014 import LoadedCandidate
from pharos.control_network_v014 import reject_ambient_network_environment
from pharos.control_population_v014 import (
    GAIA_LOGICAL_REQUESTS,
    GaiaPlanner,
    GaiaRequestPlan,
    canonical_parent,
    derive_bp_rp_survivors,
    derive_quiet_negative,
    match_chen_exclusions,
    normalize_exclusions,
    normalize_gaia_page,
    normalize_simbad_exclusions,
    simbad_upload,
)
from pharos.control_provenance_v014 import producer_identity, repository_root

FREEZE_COMMIT: Final = "07ca855920cb2209d7f9c78794fa85671e2793d3"
PREREGISTRATION_RELATIVE: Final = Path("pre_registration/v0.1.4_control_population.md")
FROZEN_RELATIVE: Final = Path("pre_registration/FROZEN.md")


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    blockers: tuple[str, ...]


def verify_frozen_registration() -> None:
    root = repository_root()
    prereg = root / PREREGISTRATION_RELATIVE
    if prereg.stat(follow_symlinks=False).st_size != 17_714 or sha256_file(prereg) != (
        "ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b"
    ):
        raise RuntimeError("frozen v0.1.4 pre-registration bytes do not match")
    frozen = (root / FROZEN_RELATIVE).read_text(encoding="utf-8")
    if "17,714 bytes" not in frozen or (
        "ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b" not in frozen
    ):
        raise RuntimeError("FROZEN.md does not bind the registered v0.1.4 bytes")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", FREEZE_COMMIT, "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("producer HEAD does not descend from the freeze commit")


def preflight(
    *, publication_parent: Path, environ: dict[str, str] | None = None
) -> PreflightResult:
    """Perform all local checks without creating an attempt or using a network."""
    blockers: list[str] = []
    checks = (
        ("frozen_registration", verify_frozen_registration),
        ("ambient_network", lambda: reject_ambient_network_environment(environ)),
        ("producer_identity", producer_identity),
        ("renameatx_np", lambda: probe_rename_excl(publication_parent)),
    )
    for label, check in checks:
        try:
            check()
        except Exception as exc:  # local preflight aggregates generic findings only
            blockers.append(f"{label}: {type(exc).__name__}")
    if not trust.AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256:
        blockers.append("reviewer_trust_root: no authorized reviewer signing-key hash")
    return PreflightResult(not blockers, tuple(blockers))


def require_acquisition_preflight(
    *, publication_parent: Path, environ: dict[str, str] | None = None
) -> None:
    result = preflight(publication_parent=publication_parent, environ=environ)
    if not result.passed:
        raise RuntimeError("v0.1.4 acquisition preflight blocked: " + "; ".join(result.blockers))


@dataclass(frozen=True)
class GaiaAcquisitionSession:
    """Logical Gaia session; only validated full pages advance its cursor."""

    attempt_id: str
    planner: GaiaPlanner = GaiaPlanner()
    pages: tuple[tuple[GaiaRequestPlan, pd.DataFrame, pd.DataFrame], ...] = ()

    @classmethod
    def create(cls) -> GaiaAcquisitionSession:
        return cls(str(uuid.uuid4()))

    def next_request(self) -> GaiaRequestPlan | None:
        return self.planner.next_request()

    def accept(self, plan: GaiaRequestPlan, decoded_raw: pd.DataFrame) -> GaiaAcquisitionSession:
        normalized = normalize_gaia_page(
            decoded_raw,
            cell=plan.cell,
            cursor_before=plan.cursor_before,
            requested_rows=plan.requested_rows,
        )
        planner = self.planner.accept_page(plan, normalized)
        return GaiaAcquisitionSession(
            self.attempt_id,
            planner,
            (*self.pages, (plan, decoded_raw.copy(deep=True), normalized.copy(deep=True))),
        )

    def parent(self) -> pd.DataFrame:
        if self.planner.completed_requests != GAIA_LOGICAL_REQUESTS:
            raise RuntimeError("Gaia candidate is incomplete")
        return canonical_parent(tuple((plan, normalized) for plan, _, normalized in self.pages))

    def checkpoint_semantic_identity(self) -> str:
        digest = hashlib.sha256(b"pharos-gaia-checkpoint-state-v014\x00")
        digest.update(self.attempt_id.encode())
        for state in self.planner.progress:
            digest.update(state.cell.id.encode())
            digest.update(state.cursor.to_bytes(8, "little"))
            digest.update(state.collected_rows.to_bytes(8, "little"))
        return digest.hexdigest()


@dataclass(frozen=True)
class FinalDerivation:
    bp_rp_survivors: pd.DataFrame
    simbad_parts: tuple[pd.DataFrame, ...]
    chen_exclusions: pd.DataFrame | None = None
    exclusions: pd.DataFrame | None = None
    controls: pd.DataFrame | None = None


class ReleaseDerivationSession:
    """Consumes one trusted raw checkpoint and enforces external request order."""

    def __init__(self, checkpoint: LoadedCandidate, raw_parent: pd.DataFrame) -> None:
        if not checkpoint.trusted or checkpoint.registry_entry_id is None:
            raise PermissionError(
                "release derivation requires an exactly registered raw checkpoint"
            )
        self.checkpoint = checkpoint
        self.state = FinalDerivation(derive_bp_rp_survivors(raw_parent), ())

    @property
    def simbad_request_count(self) -> int:
        return (len(self.state.bp_rp_survivors) + 499) // 500

    def next_simbad_input(self) -> pd.DataFrame | None:
        sequence = len(self.state.simbad_parts)
        if sequence == self.simbad_request_count:
            return None
        start = sequence * 500
        return simbad_upload(self.state.bp_rp_survivors.iloc[start : start + 500])

    def accept_simbad(self, decoded_raw: pd.DataFrame) -> pd.DataFrame:
        upload = self.next_simbad_input()
        if upload is None:
            raise RuntimeError("all registered SIMBAD parent slices are already complete")
        normalized = normalize_simbad_exclusions(decoded_raw, upload, self.state.bp_rp_survivors)
        self.state = FinalDerivation(
            self.state.bp_rp_survivors,
            (*self.state.simbad_parts, normalized.copy(deep=True)),
        )
        return normalized

    def accept_chen(self, decoded_raw: pd.DataFrame) -> FinalDerivation:
        if self.next_simbad_input() is not None:
            raise RuntimeError("Chen request cannot precede the complete SIMBAD partition")
        if self.state.chen_exclusions is not None:
            raise RuntimeError("Chen catalog response is already complete")
        chen = match_chen_exclusions(decoded_raw, self.state.bp_rp_survivors)
        exclusions = normalize_exclusions(self.state.simbad_parts, chen, self.state.bp_rp_survivors)
        controls = derive_quiet_negative(self.state.bp_rp_survivors, exclusions)
        self.state = FinalDerivation(
            self.state.bp_rp_survivors,
            self.state.simbad_parts,
            chen,
            exclusions,
            controls,
        )
        return self.state

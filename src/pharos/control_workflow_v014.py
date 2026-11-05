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
from typing import Any, Final

import pandas as pd

from pharos import control_transport_v014 as transport_module
from pharos import trusted_control_releases_v014 as trust
from pharos.control_artifacts_v014 import probe_rename_excl, sha256_file
from pharos.control_loaders_v014 import LoadedCandidate
from pharos.control_manifests_v014 import append_state_event
from pharos.control_network_v014 import (
    CA_BUNDLE_FILENAME,
    CA_BUNDLE_SHA256,
    reject_ambient_network_environment,
)
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
from pharos.control_schemas_v014 import GAIA_TABLE_COLUMNS

FREEZE_COMMIT: Final = "90fbea1d45e3573f65ed9eee827c91b65699ad49"
PREREGISTRATION_RELATIVE: Final = Path("pre_registration/v0.1.7_parser_containment_repair.md")
FROZEN_RELATIVE: Final = Path("pre_registration/FROZEN.md")


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    blockers: tuple[str, ...]


def verify_frozen_registration() -> None:
    root = repository_root()
    prereg = root / PREREGISTRATION_RELATIVE
    if prereg.stat(follow_symlinks=False).st_size != 4_454 or sha256_file(prereg) != (
        "62f1b74efd85fb6f36203094c27a947bf2a16e77c0b5ee428a749e55142aeb49"
    ):
        raise RuntimeError("frozen v0.1.7 pre-registration bytes do not match")
    frozen = (root / FROZEN_RELATIVE).read_text(encoding="utf-8")
    if "4,454 bytes" not in frozen or (
        "7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d" not in frozen
    ):
        raise RuntimeError("FROZEN.md does not bind the registered v0.1.7 bytes")
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


def read_status_authorization(repository: Path) -> dict[str, bool]:
    """Read the operator authorization boundary; fail closed on any defect.

    AGENTS.md mechanical control: an acquisition entry point must refuse
    false, missing, or malformed authorization rather than defaulting.
    """
    import tomllib

    path = repository / "status.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PermissionError(f"status boundary unreadable: {type(exc).__name__}") from exc
    authorization = document.get("authorization")
    if not isinstance(authorization, dict) or not authorization:
        raise PermissionError("status boundary has no authorization section")
    result: dict[str, bool] = {}
    for key, value in authorization.items():
        if type(value) is not bool:
            raise PermissionError(f"authorization key {key!r} is not boolean")
        result[key] = value
    return result


def require_status_authorization(repository: Path, *keys: str) -> None:
    authorization = read_status_authorization(repository)
    missing = [key for key in keys if key not in authorization]
    if missing:
        raise PermissionError(f"status boundary lacks authorization keys: {missing}")
    refused = [key for key in keys if not authorization[key]]
    if refused:
        raise PermissionError(f"operator authorization refused: {refused}")


def stage_registered_ca_bundle(repository: Path) -> Path:
    """Stage the environment certifi bundle under its registered name."""
    import certifi

    destination = repository / "controls" / CA_BUNDLE_FILENAME
    if destination.exists():
        return destination
    source = Path(certifi.where())
    payload = source.read_bytes()
    import hashlib

    if hashlib.sha256(payload).hexdigest() != CA_BUNDLE_SHA256:
        raise PermissionError("environment certifi bundle does not match the registration")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".staging")
    temporary.write_bytes(payload)
    temporary.chmod(0o600)
    temporary.replace(destination)
    return destination


def run_gaia_acquisition(
    *,
    publication_parent: Path,
    ca_bundle_path: Path,
    transport: Any = transport_module,
    attempt_id: str | None = None,
) -> tuple[Path, str]:
    """Execute the frozen v0.1.4 Gaia acquisition and publish the checkpoint.

    Runs the exact 120-logical-page plan from cursor zero under the frozen
    transport policy, journals every transport attempt, and no-replace
    publishes the candidate checkpoint tree. Requires operator authorization
    and a passing preflight before any network byte moves.
    """
    from pharos import control_packaging_v014 as packaging

    publication_parent = publication_parent.resolve(strict=True)
    require_acquisition_preflight(publication_parent=publication_parent)
    session = GaiaAcquisitionSession.create()
    attempt_id = attempt_id or session.attempt_id
    if attempt_id != session.attempt_id:
        raise ValueError("explicit attempt id must match the fresh session identity")
    attempts_root = publication_parent / "attempts"
    attempts_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    attempt_directory = attempts_root / attempt_id
    attempt_directory.mkdir(mode=0o700)
    state_path = attempt_directory / "attempt_state.jsonl"
    evidence_init = __import__("hashlib").sha256(
        b"pharos-v0.1.4:" + attempt_id.encode("ascii")
    ).hexdigest()
    append_state_event(
        state_path,
        attempt_id=attempt_id,
        to_state="initialized",
        actor_role="gaia_acquisition_worker",
        evidence_semantic_sha256=evidence_init,
    )
    append_state_event(
        state_path,
        attempt_id=attempt_id,
        to_state="gaia_acquiring",
        actor_role="gaia_acquisition_worker",
        evidence_semantic_sha256=evidence_init,
    )
    journal = transport.TransportJournal(attempt_id)
    while True:
        plan = session.next_request()
        if plan is None:
            break
        spool = transport.execute_tap_async(
            service="gaia",
            query_text=plan.query_text,
            journal=journal,
            logical_request_id=plan.logical_request_id,
            attempt_directory=attempt_directory,
            ca_bundle_path=ca_bundle_path,
        )
        decoded = transport.decode_votable_table(
            spool,
            tuple(
                (column.name, column.logical_type, column.nullable)
                for column in GAIA_TABLE_COLUMNS
            ),
        )
        session = session.accept(plan, decoded)
    append_state_event(
        state_path,
        attempt_id=attempt_id,
        to_state="gaia_candidate_complete",
        actor_role="gaia_acquisition_worker",
        evidence_semantic_sha256=session.checkpoint_semantic_identity(),
    )
    checkpoints_parent = publication_parent / "checkpoints" / "quiet_negative_v0.1.4"
    checkpoints_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    checkpoint_path = packaging.publish_gaia_checkpoint(
        session=session,
        transport_attempts=journal.to_frame(),
        attempt_state_bytes=state_path.read_bytes(),
        output_parent=checkpoints_parent,
        ca_bundle_path=ca_bundle_path,
    )
    return checkpoint_path, attempt_id

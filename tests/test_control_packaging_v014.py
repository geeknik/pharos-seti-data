from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from pharos import control_packaging_v014 as packaging
from pharos.control_artifacts_v014 import CandidateTreeWriter
from pharos.control_evidence_v014 import TRANSPORT_COLUMNS
from pharos.control_provenance_v014 import ProducerIdentity
from pharos.control_workflow_v014 import GaiaAcquisitionSession


def test_incomplete_session_fails_before_staging_is_created(tmp_path: Path) -> None:
    session = GaiaAcquisitionSession.create()

    with pytest.raises(RuntimeError, match="Gaia candidate is incomplete"):
        packaging.publish_gaia_checkpoint(
            session=session,
            transport_attempts=pd.DataFrame(columns=TRANSPORT_COLUMNS),
            attempt_state_bytes=b"invalid state is never reached",
            output_parent=tmp_path,
            ca_bundle_path=tmp_path / "unused.pem",
        )

    assert list(tmp_path.iterdir()) == []


def test_packager_failure_closes_descriptors_and_preserves_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = GaiaAcquisitionSession.create()
    captured: list[CandidateTreeWriter] = []

    class CapturingWriter(CandidateTreeWriter):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            captured.append(self)

    monkeypatch.setattr(GaiaAcquisitionSession, "parent", lambda _self: pd.DataFrame())
    monkeypatch.setattr(packaging, "_state_bytes_validated", lambda *_args: None)
    monkeypatch.setattr(
        packaging,
        "producer_identity",
        lambda: ProducerIdentity("1" * 40, "2" * 64, "3" * 64),
    )
    monkeypatch.setattr(packaging, "CandidateTreeWriter", CapturingWriter)
    monkeypatch.setattr(
        packaging,
        "_software_payloads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced packaging failure")),
    )

    with pytest.raises(RuntimeError, match="forced packaging failure"):
        packaging.publish_gaia_checkpoint(
            session=session,
            transport_attempts=pd.DataFrame(columns=TRANSPORT_COLUMNS),
            attempt_state_bytes=b"ignored by focused failure injection",
            output_parent=tmp_path,
            ca_bundle_path=tmp_path / "unused.pem",
        )

    assert len(captured) == 1
    writer = captured[0]
    with pytest.raises(OSError):
        os.fstat(writer.staging_fd)
    with pytest.raises(OSError):
        os.fstat(writer.parent_fd)
    assert writer.staging_path.is_dir()
    assert list(writer.staging_path.glob("pre_registration.v0.1.4.*.md"))
    assert not (writer.staging_path / "checkpoint_manifest.yaml").exists()
    writer.close_unpublished()
    writer.close()

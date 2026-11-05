"""Offline transport and acquisition-runner tests; no network by construction."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from pharos import control_manifests_v014 as manifests
from pharos import control_population_v014 as population
from pharos import control_transport_v014 as transport
from pharos import control_workflow_v014 as workflow
from tests.test_control_population_v014 import valid_page


def _write_status(root: Path, body: str) -> None:
    (root / "status.toml").write_text(body, encoding="utf-8")


def test_status_authorization_refuses_false_missing_and_malformed(tmp_path: Path) -> None:
    _write_status(tmp_path, '[authorization]\ncatalog_acquisition = false\n')
    authorization = workflow.read_status_authorization(tmp_path)
    assert authorization["catalog_acquisition"] is False
    with pytest.raises(PermissionError):
        workflow.require_status_authorization(tmp_path, "catalog_acquisition")

    _write_status(tmp_path, "[authorization]\n")
    with pytest.raises(PermissionError):
        workflow.require_status_authorization(tmp_path, "catalog_acquisition")

    _write_status(tmp_path, '[authorization]\ncatalog_acquisition = "yes"\n')
    with pytest.raises(PermissionError):
        workflow.read_status_authorization(tmp_path)

    (tmp_path / "status.toml").unlink()
    with pytest.raises(PermissionError):
        workflow.read_status_authorization(tmp_path)


def test_status_authorization_passes_only_when_granted(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        '[authorization]\ncatalog_acquisition = true\ncheckpoint_creation = true\n',
    )
    workflow.require_status_authorization(
        tmp_path, "catalog_acquisition", "checkpoint_creation"
    )


def test_transport_journal_rows_match_the_registered_schema() -> None:
    journal = transport.TransportJournal("0f1e2d3c-4b5a-4678-9abc-def012345678")
    frame = journal.to_frame()
    assert len(frame) == 0
    from pharos.control_evidence_v014 import TRANSPORT_COLUMNS

    assert tuple(frame.columns) == tuple(TRANSPORT_COLUMNS)


class _FakeTransport:
    """Deterministic offline transport driving a parallel planner in lockstep."""

    def __init__(self) -> None:
        self.journal: transport.TransportJournal | None = None
        self.planner = population.GaiaPlanner()
        self.pages: dict[str, pd.DataFrame] = {}
        self.next_id = {ordinal: (ordinal + 1) * 1_000_000 + 1 for ordinal in range(24)}

    def TransportJournal(  # noqa: N802
        self, attempt_id: str, persist_path: Path | None = None
    ) -> transport.TransportJournal:
        self.journal = transport.TransportJournal(attempt_id, persist_path=persist_path)
        return self.journal

    def execute_tap_async(
        self,
        *,
        service: str,
        query_text: str,
        journal: transport.TransportJournal,
        logical_request_id: str,
        attempt_directory: Path,
        ca_bundle_path: Path,
    ) -> Path:
        assert service == "gaia"
        plan = self.planner.next_request()
        assert plan is not None and plan.logical_request_id == logical_request_id
        ids: list[int] = []
        for _ in range(plan.requested_rows):
            ids.append(self.next_id[plan.cell.ordinal])
            self.next_id[plan.cell.ordinal] += 1
        page = valid_page(ids, cell=plan.cell)
        self.planner = self.planner.accept_page(plan, page)
        self.pages[logical_request_id] = page
        stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        journal._append(
            logical_request_id=logical_request_id,
            phase="fetch",
            started=stamp,
            finished=stamp,
            outcome="success",
            status=200,
            hostname="gea.esac.esa.int",
            peer_ip="193.147.152.102",
            leaf_certificate_sha256="e" * 64,
            exchange=None,
            error_code=None,
        )
        return Path(f"offline-{logical_request_id}")

    def decode_votable_table(
        self, spool_path: Path, expected_columns: Any
    ) -> pd.DataFrame:
        return self.pages[spool_path.name.removeprefix("offline-")]


def test_run_gaia_acquisition_publishes_a_valid_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import certifi

    from pharos import control_packaging_v014 as packaging
    from pharos.control_network_v014 import CA_BUNDLE_SHA256

    monkeypatch.setattr(workflow, "require_acquisition_preflight", lambda **_kwargs: None)
    monkeypatch.setattr(
        packaging,
        "producer_identity",
        lambda: SimpleNamespace(
            git_commit="a" * 40,
            source_tree_sha256="1" * 64,
            uv_lock_sha256="2" * 64,
        ),
    )

    def fake_payloads(writer, identity, *, ca_bundle_path):
        # The registered release platform (frozen Section 16) is enforced by
        # the real builder; this offline runner test substitutes exact-shape
        # payloads so only the runner/packager wiring is under test.
        source = packaging._write_text(
            writer,
            f"software/pharos-seti-data-v0.1.4-source.{'a' * 64}.tar",
            b"source-distribution-stub",
            schema_version="pharos.source-distribution.v1",
        )
        lock = packaging._write_text(
            writer,
            f"software/uv.lock.{'b' * 64}.txt",
            b"lock-stub",
            schema_version="pharos.uv-lock.v1",
        )
        toolchain = packaging._write_text(
            writer,
            f"software/toolchain.{'c' * 64}.yaml",
            b"toolchain-stub",
            schema_version="pharos.toolchain.v1",
        )
        normalizers = packaging._write_text(
            writer,
            f"software/normalizer_registry.{'d' * 64}.yaml",
            b"normalizer-registry-stub",
            schema_version="pharos.normalizer-registry.v1",
        )
        ca = packaging._write_text(
            writer,
            f"software/ca_bundle.{CA_BUNDLE_SHA256}.pem",
            Path(certifi.where()).read_bytes(),
            schema_version="pharos.ca-bundle.v1",
        )
        return (
            {
                "source_distribution": source,
                "uv_lock": lock,
                "toolchain": toolchain,
                "normalizer_registry": normalizers,
                "ca_bundle": ca,
            },
            {},
        )

    monkeypatch.setattr(packaging, "_software_payloads", fake_payloads)
    fake = _FakeTransport()

    checkpoint_path, attempt_id = workflow.run_gaia_acquisition(
        publication_parent=tmp_path,
        ca_bundle_path=Path(certifi.where()),
        transport=fake,
    )

    manifest_file = checkpoint_path / "checkpoint_manifest.yaml"
    assert manifest_file.is_file()
    manifest = manifests.strict_yaml_load(manifest_file)
    manifests.validate_checkpoint_manifest(manifest)
    assert manifest["attempt_id"] == attempt_id
    assert manifest["gaia_logical_requests"] == 120
    selection = manifest["selection"]
    assert sum(cell["collected_rows"] for cell in selection["cells"]) == 55_000

    assert fake.journal is not None
    logical_ids = {record.logical_request_id for record in fake.journal.records}
    assert len(logical_ids) == 120

    state_bytes = (tmp_path / "attempts" / attempt_id / "attempt_state.jsonl").read_bytes()
    events = [json.loads(line) for line in state_bytes.splitlines()]
    assert manifests.validate_state_events(events) == "gaia_candidate_complete"

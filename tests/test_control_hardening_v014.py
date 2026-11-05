from __future__ import annotations

import json
import uuid
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from pharos import control_artifacts_v014 as artifacts
from pharos import control_loaders_v014 as loaders
from pharos import control_manifests_v014 as manifests
from pharos import trusted_control_releases_v014 as trust

V7 = "62f1b74efd85fb6f36203094c27a947bf2a16e77c0b5ee428a749e55142aeb49"
V6 = "54f7d67ffedc931c9784308aac9be325bd2644aaa0ed1391f1b4293c3fa2a650"
V4 = "ecc752928a179f9d533997349f722ca5eb9dee1ccbc9635ead865a207b64a96b"
V3 = "b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43"


@pytest.mark.parametrize("directory", ["", "."])
def test_content_addressed_parquet_can_be_written_at_candidate_root(
    tmp_path: Path, directory: str
) -> None:
    columns = (artifacts.Column("id", "int64", False),)
    writer = artifacts.CandidateTreeWriter(tmp_path, f"candidate-{directory == '.'}")
    identity = writer.write_content_addressed_parquet(
        directory,
        "raw_candidates",
        pd.DataFrame({"id": [1]}),
        schema_version="test.root-parquet.v1",
        columns=columns,
        source_tree_sha256="1" * 64,
        uv_lock_sha256="2" * 64,
    )
    assert "/" not in identity.path
    published = writer.publish(b"schema_version: test\n")
    assert (published / identity.path).is_file()


def test_content_addressed_parquet_rejects_unsafe_directory(tmp_path: Path) -> None:
    columns = (artifacts.Column("id", "int64", False),)
    writer = artifacts.CandidateTreeWriter(tmp_path, "candidate")
    with pytest.raises(ValueError, match="artifact path"):
        writer.write_content_addressed_parquet(
            "../escape",
            "raw_candidates",
            pd.DataFrame({"id": [1]}),
            schema_version="test.root-parquet.v1",
            columns=columns,
            source_tree_sha256="1" * 64,
            uv_lock_sha256="2" * 64,
        )


def test_semantic_frame_is_stable_and_normalizes_negative_zero() -> None:
    columns = (
        artifacts.Column("id", "int64", False),
        artifacts.Column("value", "float64", False),
        artifacts.Column("label", "string", True),
    )
    first = pd.DataFrame({"id": [1], "value": [-0.0], "label": [None]})
    second = pd.DataFrame({"id": [1], "value": [0.0], "label": [None]})
    assert artifacts.semantic_sha256(first, "test.schema", columns) == artifacts.semantic_sha256(
        second, "test.schema", columns
    )
    changed = second.copy()
    changed.loc[0, "value"] = 1.0
    assert artifacts.semantic_sha256(first, "test.schema", columns) != artifacts.semantic_sha256(
        changed, "test.schema", columns
    )


@pytest.mark.parametrize(
    "path",
    ["../escape", "/absolute", r"C:\\drive", "a//b", "a/./b", "a\\b", "\x00"],
)
def test_relative_paths_fail_closed(path: str) -> None:
    with pytest.raises(ValueError):
        artifacts.validate_relative_path(path)


@pytest.mark.parametrize(
    "raw",
    [
        b"a: 1\na: 2\n",
        b"a: &x 1\nb: *x\n",
        b"? [a, b]\n: 1\n",
        b"a: !custom payload\n",
    ],
)
def test_strict_yaml_rejects_duplicate_alias_nonstring_and_custom_tag(raw: bytes) -> None:
    with pytest.raises((TypeError, ValueError, yaml_error())):
        manifests.strict_yaml_load_bytes(raw)


def yaml_error() -> type[Exception]:
    import yaml

    return yaml.YAMLError


def test_attempt_state_chain_and_transition_fail_closed(tmp_path: Path) -> None:
    attempt_id = str(uuid.uuid4())
    path = tmp_path / "attempt_state.jsonl"
    manifests.append_state_event(
        path,
        attempt_id=attempt_id,
        to_state="initialized",
        actor_role="gaia_acquisition_worker",
        evidence_semantic_sha256="1" * 64,
    )
    manifests.append_state_event(
        path,
        attempt_id=attempt_id,
        to_state="gaia_acquiring",
        actor_role="gaia_acquisition_worker",
        evidence_semantic_sha256="2" * 64,
    )
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert manifests.validate_state_events(events) == "gaia_acquiring"
    with pytest.raises(ValueError, match="transition"):
        manifests.append_state_event(
            path,
            attempt_id=attempt_id,
            to_state="external_acquiring",
            actor_role="gaia_acquisition_worker",
            evidence_semantic_sha256="3" * 64,
        )


def test_reviewer_trust_root_is_pinned_and_fail_closed() -> None:
    # Frozen v0.1.4 Section 5.2 pins exactly this operator-designated key.
    assert trust.AUTHORIZED_REVIEWER_SIGNING_KEY_SHA256 == (
        "119b9e83dd61e470b8fa52c2269403b45958a7cfaca7a26e2142478a44fb9f07",
    )
    assert loaders.validated_registry() == ((), ())
    with pytest.raises(PermissionError, match="not exactly authorized"):
        loaders.load_registered_final_release("missing", Path.cwd())


def test_final_raw_producer_rejects_embedded_distribution_shape() -> None:
    """Frozen v0.1.4 Section 5.1: the final manifest's raw producer is bound by
    registered-checkpoint reference and must not carry a distribution slot."""
    v013_style_record: dict[str, object] = {
        "git_commit": "a" * 40,
        "source_tree_sha256": "b" * 64,
        "uv_lock_sha256": "c" * 64,
        "toolchain_sha256": "d" * 64,
        "source_distribution": {
            "path": "software/pharos-seti-data-v0.1.4-source.tar",
            "byte_sha256": "e" * 64,
            "semantic_sha256": None,
            "bytes": 1,
            "rows": None,
            "schema_version": "pharos.source-archive.v1",
            "columns": None,
            "producer_role": "raw",
        },
    }
    with pytest.raises(ValueError, match="RawProducerReference"):
        manifests.validate_raw_producer_reference(v013_style_record)


def test_raw_producer_reference_requires_checkpoint_binding() -> None:
    record: dict[str, object] = {
        "git_commit": "a" * 40,
        "source_tree_sha256": "b" * 64,
        "uv_lock_sha256": "c" * 64,
        "toolchain_sha256": "d" * 64,
        "raw_checkpoint_registry_entry_id": "raw-entry-1",
        "raw_checkpoint_manifest_path": "controls/checkpoints/quiet_negative_v0.1.4/a/checkpoint_manifest.yaml",
        "raw_checkpoint_manifest_byte_sha256": "f" * 64,
    }
    validated = manifests.validate_raw_producer_reference(record)
    assert validated["raw_checkpoint_registry_entry_id"] == "raw-entry-1"
    for mutation in (
        dict(record, raw_checkpoint_manifest_path="/absolute/manifest.yaml"),
        dict(record, raw_checkpoint_registry_entry_id=""),
        dict(record, raw_checkpoint_manifest_byte_sha256="short"),
    ):
        with pytest.raises(ValueError):
            manifests.validate_raw_producer_reference(mutation)


def test_incorporated_preregistrations_are_pinned_to_frozen_digests() -> None:
    """Frozen v0.1.5 Section 2.2: exactly v0.1.4 then v0.1.3, hash-bound."""
    V5 = "7c14f53fbf4883c0ba0cb941c547a4e3a3d545a53d1dd16b5bcc72bbdd97ec2d"
    entries = [
        {"path": f"pre_registration.v0.1.7.{V7}.md", "byte_sha256": V7},
        {"path": f"pre_registration.v0.1.6.{V6}.md", "byte_sha256": V6},
        {"path": f"pre_registration.v0.1.5.{V5}.md", "byte_sha256": V5},
        {"path": f"pre_registration.v0.1.4.{V4}.md", "byte_sha256": V4},
        {"path": f"pre_registration.v0.1.3.{V3}.md", "byte_sha256": V3},
    ]
    base: dict[str, object] = {"incorporated_pre_registrations": entries}
    manifests._validate_incorporated_preregistration(base)
    for mutation in (
        {"incorporated_pre_registrations": entries[:4]},
        {"incorporated_pre_registrations": list(reversed(entries))},
        {"incorporated_pre_registrations": [{"path": "../escape.md", "byte_sha256": V4}, *entries[1:]]},
        {"incorporated_pre_registrations": [dict(entries[0], byte_sha256="0" * 64), *entries[1:]]},
    ):
        with pytest.raises(ValueError):
            manifests._validate_incorporated_preregistration(mutation)


def test_registered_raw_checkpoint_verifies_every_artifact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    manifest_path = root / "checkpoint_manifest.yaml"
    manifest_path.write_bytes(b"schema_version: test\n")
    first = b"first-valid-artifact"
    second = b"second-tampered-artifact"
    (root / "first.bin").write_bytes(first)
    (root / "second.bin").write_bytes(second)
    entry: dict[str, object] = {
        "entry_id": "raw-test",
        "manifest_path": "candidate/checkpoint_manifest.yaml",
        "manifest_byte_sha256": artifacts.sha256_file(manifest_path),
        "artifact_identities": (
            (
                "first.bin",
                hashlib.sha256(first).hexdigest(),
                None,
                len(first),
                None,
                "binary",
                None,
            ),
            (
                "second.bin",
                "0" * 64,
                None,
                len(second),
                None,
                "binary",
                None,
            ),
        ),
    }
    monkeypatch.setattr(loaders, "validated_registry", lambda: ((entry,), ()))
    monkeypatch.setattr(loaders, "_verify_review_chain", lambda *_args: None)
    monkeypatch.setattr(loaders, "strict_yaml_load", lambda _path: {})
    monkeypatch.setattr(loaders, "validate_checkpoint_manifest", lambda _value: None)
    monkeypatch.setattr(loaders, "_verify_packaged_prereg", lambda *_args: None)

    with pytest.raises(ValueError, match="registered artifact identity mismatch"):
        loaders.load_registered_raw_checkpoint("raw-test", tmp_path)


def test_review_attestation_cannot_pass_empty_trust_root() -> None:
    attempt_id = str(uuid.uuid4())
    checks = [
        {
            "check_id": name,
            "passed": True,
            "evidence_path": "evidence.txt",
            "evidence_sha256": "1" * 64,
            "summary": "passed",
        }
        for name in (
            "tree",
            "manifest",
            "schemas",
            "counts",
            "queries",
            "transport",
            "resources",
            "reconstruction",
        )
    ]
    value = {
        "schema_version": "pharos.control-review-attestation.v0.1.4",
        "review_role": "raw_checkpoint",
        "attempt_id": attempt_id,
        "candidate_commit": "1" * 40,
        "candidate_manifest_path": "controls/checkpoint_manifest.yaml",
        "candidate_manifest_byte_sha256": "2" * 64,
        "pre_registration_byte_sha256": "9c1751721a2021c632a8a86cfab6a67e1f23e1bcc84973a25dc156b2b5bc7999",
        "reviewer_identity": "reviewer",
        "reviewer_signing_key_sha256": "3" * 64,
        "reviewed_at_utc": "2026-08-06T00:00:00.000000Z",
        "artifact_identities": [
            {
                "path": "x",
                "byte_sha256": "4" * 64,
                "semantic_sha256": None,
                "bytes": 1,
                "rows": None,
                "schema_version": "text",
                "columns": None,
            }
        ],
        "checks": checks,
        "outcome": "approved",
        "notes": "",
    }
    with pytest.raises(PermissionError, match="empty or unauthorized"):
        manifests.validate_review_attestation(value, ())

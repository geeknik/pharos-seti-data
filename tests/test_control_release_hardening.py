"""Regression tests for hardened control acquisition and publication boundaries."""

from __future__ import annotations

import argparse
import copy
import hashlib
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from pharos import artifacts, calibration, cli, control_population, sources, validation
from tests.test_control_population import _joined_sources, _valid_manifest


def _trusted_release_for_manifest(
    manifest_path: Path,
    *,
    release_id: str = "test-authorized-release",
) -> artifacts.TrustedFinalRelease:
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    frames = {
        name: pd.read_parquet(manifest_path.parent / descriptor["path"])
        for name, descriptor in payload["artifacts"].items()
    }

    def trusted_artifact(name: str) -> artifacts.TrustedReleaseArtifact:
        descriptor = payload["artifacts"][name]
        return artifacts.TrustedReleaseArtifact(
            path=descriptor["path"],
            sha256=descriptor["sha256"],
            row_count=descriptor["row_count"],
            columns=tuple(descriptor["columns"]),
            schema_version=descriptor["schema_version"],
            content_sha256=artifacts.sha256_frame(frames[name]),
        )

    traces = payload["query_provenance"]
    gaia_traces = [trace for trace in traces if trace["service"] == "Gaia TAP joined"]
    simbad_traces = [trace for trace in traces if trace["service"] == "SIMBAD"]
    chen_trace = next(trace for trace in traces if trace["service"] == "VizieR Chen2014")
    exclusions = frames["exclusions"]
    software = payload["software"]
    return artifacts.TrustedFinalRelease(
        release_id=release_id,
        manifest_sha256=artifacts.sha256_file(manifest_path),
        producer_software=(
            software["git_commit"],
            software["source_tree_sha256"],
            software["uv_lock_sha256"],
        ),
        raw_candidates=trusted_artifact("raw_candidates"),
        controls=trusted_artifact("controls"),
        exclusions=trusted_artifact("exclusions"),
        query_provenance_sha256=artifacts._trace_identity_sha256(traces),  # noqa: SLF001
        gaia_query_hashes_sha256=artifacts.sha256_strings(
            [trace["query_sha256"] for trace in gaia_traces]
        ),
        simbad_query_sha256=simbad_traces[0]["query_sha256"],
        simbad_raw_response_rows=sum(trace["response_rows"] for trace in simbad_traces),
        simbad_normalized_rows=int(
            (exclusions["exclusion_catalog"] == "SIMBAD").sum()
        ),
        chen_query_sha256=chen_trace["query_sha256"],
        chen_response_rows=chen_trace["response_rows"],
        chen_normalized_rows=int(
            (exclusions["exclusion_catalog"] == "Chen2014").sum()
        ),
    )


def test_software_provenance_refuses_dirty_tracked_and_untracked_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    package = root / "src" / "pharos"
    package.mkdir(parents=True)
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "src/pharos", "pyproject.toml", "uv.lock"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    monkeypatch.setattr(artifacts, "repository_root", lambda: root)

    clean = artifacts.software_provenance()
    assert len(clean["git_commit"]) == 40

    (package / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dirty"):
        artifacts.software_provenance()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "untracked.py").write_text("PAYLOAD = True\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dirty"):
        artifacts.software_provenance()

    def forbid_acquisition(*args: object, **kwargs: object) -> None:
        raise AssertionError("dirty publication attempted remote acquisition")

    monkeypatch.setattr(sources, "fetch_quiet_negative_controls", forbid_acquisition)
    with pytest.raises(RuntimeError, match="dirty"):
        control_population.reproduce_failed_v012_pilot(
            output_dir=root / control_population.FAILED_V012_OUTPUT_RELATIVE,
            raw_cache_path=root / control_population.FAILED_V012_RAW_CACHE_RELATIVE,
            minimum_joined_rows=1,
            generating_command="python -m pharos.cli reproduce_failed_v012_pilot",
        )


def test_sampling_plan_is_deterministic_all_sky_and_exact_quota() -> None:
    first = sources.build_sampling_strata(55_000)
    second = sources.build_sampling_strata(55_000)
    assert first == second
    assert len(first) == 24
    assert sum(item.quota for item in first) == 55_000
    assert {item.hemisphere for item in first} == {"north", "south"}
    assert {(item.longitude_min_deg, item.longitude_max_deg) for item in first} == {
        (float(lower), float(lower + 30)) for lower in range(0, 360, 30)
    }
    assert max(item.quota for item in first) - min(item.quota for item in first) <= 1


def test_failed_pilot_release_identity_is_not_authorized() -> None:
    pilot_manifest_sha256 = (
        "da275acc872318283ada59fafe6ba93613c669d0f34452dc931f0b3763aa0d8c"
    )
    assert all(
        release.manifest_sha256 != pilot_manifest_sha256
        for release in artifacts.TRUSTED_FINAL_RELEASES
    )


def test_fresh_current_producer_candidate_requires_registry_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    reviewed = artifacts.validate_control_release_candidate(manifest_path)
    assert reviewed["gaia_dr3_source_id"].tolist() == [1, 2]

    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", ())
    with pytest.raises(ValueError, match="registry-authorized"):
        artifacts.load_control_artifact(
            manifest_path,
            release_id="fresh-current-producer",
        )


def test_exact_registry_authorization_is_required_and_sufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    trusted = _trusted_release_for_manifest(manifest_path)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (trusted,))

    with pytest.raises(ValueError, match="non-empty registry key"):
        artifacts.load_control_artifact(manifest_path, release_id="")
    with pytest.raises(ValueError, match="invalid syntax"):
        artifacts.load_control_artifact(manifest_path, release_id="../candidate")
    with pytest.raises(ValueError, match="registry-authorized"):
        artifacts.load_control_artifact(manifest_path, release_id="unknown-release")

    loaded = artifacts.load_control_artifact(
        manifest_path,
        release_id=trusted.release_id,
    )
    assert loaded["gaia_dr3_source_id"].tolist() == [1, 2]


@pytest.mark.parametrize(
    "registry",
    [None, {}, [], object(), (None,), ({"release_id": "forged"},), (object(),)],
)
def test_malformed_release_registry_fails_with_controlled_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: object,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", registry)
    with pytest.raises(artifacts.ReleaseRegistryError, match="release registry"):
        artifacts.load_authorized_control_release(
            manifest_path,
            release_id="test-authorized-release",
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("release_id", "../invalid"),
        ("manifest_sha256", "not-a-digest"),
        ("producer_software", None),
        ("raw_candidates", None),
        ("simbad_raw_response_rows", True),
    ],
)
def test_malformed_typed_registry_entry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: object,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    trusted = _trusted_release_for_manifest(manifest_path)
    malformed = replace(trusted, **{field: bad_value})
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (malformed,))
    with pytest.raises(artifacts.ReleaseRegistryError, match="release registry"):
        artifacts.load_authorized_control_release(
            manifest_path,
            release_id="test-authorized-release",
        )


def test_duplicate_release_registry_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    trusted = _trusted_release_for_manifest(manifest_path)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (trusted, trusted))
    with pytest.raises(artifacts.ReleaseRegistryError, match="duplicate"):
        artifacts.load_authorized_control_release(
            manifest_path,
            release_id=trusted.release_id,
        )


@pytest.mark.parametrize(
    "registry",
    [None, {}, [], object(), (None,), ({"artifact_sha256": "a" * 64},), (object(),)],
)
def test_malformed_raw_checkpoint_registry_fails_with_controlled_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: object,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(artifacts, "TRUSTED_RAW_CHECKPOINTS", registry)
    with pytest.raises(artifacts.ReleaseRegistryError, match="raw checkpoint registry"):
        artifacts.validate_control_manifest(payload)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("git_commit", "invalid"),
        ("source_tree_sha256", None),
        ("uv_lock_sha256", "0" * 64),
        ("artifact_sha256", object()),
        ("manifest_sha256", "short"),
        ("content_sha256", {}),
        ("row_count", None),
        ("row_count", True),
        ("row_count", validation.MAX_RAW_CONTROL_ROWS + 1),
    ],
)
def test_malformed_typed_raw_checkpoint_entry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: object,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    trusted = artifacts.TRUSTED_RAW_CHECKPOINTS[0]
    malformed = replace(trusted, **{field: bad_value})
    monkeypatch.setattr(artifacts, "TRUSTED_RAW_CHECKPOINTS", (malformed,))
    with pytest.raises(
        artifacts.ReleaseRegistryError,
        match=r"(?:raw checkpoint registry|release registry raw_entries)",
    ):
        artifacts.validate_control_manifest(payload)


def test_duplicate_raw_checkpoint_entries_and_identities_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    trusted = artifacts.TRUSTED_RAW_CHECKPOINTS[0]
    monkeypatch.setattr(artifacts, "TRUSTED_RAW_CHECKPOINTS", (trusted, trusted))
    with pytest.raises(artifacts.ReleaseRegistryError, match="duplicate entry"):
        artifacts.validate_control_manifest(payload)

    distinct_producer = replace(trusted, git_commit="4" * 40)
    monkeypatch.setattr(
        artifacts,
        "TRUSTED_RAW_CHECKPOINTS",
        (trusted, distinct_producer),
    )
    with pytest.raises(artifacts.ReleaseRegistryError, match="duplicate .* identity"):
        artifacts.validate_control_manifest(payload)


def test_failed_non_authorizing_manifest_cannot_enter_scientific_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    trusted = _trusted_release_for_manifest(manifest_path)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema_version": control_population.FAILED_PILOT_SCHEMA_VERSION,
            "status": "failed",
            "authorization": "non_authorizing",
            "failure_reason": "unregistered selection rules",
        }
    )
    artifacts.atomic_write_yaml(payload, manifest_path)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (trusted,))

    with pytest.raises(ValueError, match="unexpected|version/status"):
        artifacts.validate_control_release_candidate(manifest_path)
    with pytest.raises(ValueError, match="unexpected|version/status"):
        artifacts.load_control_artifact(
            manifest_path,
            release_id=trusted.release_id,
        )


def test_cli_exposes_only_quarantined_v012_reproduction() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["build_quiet_negative_v012"])

    args = parser.parse_args(["reproduce_failed_v012_pilot"])
    assert args.func is cli.cmd_reproduce_failed_v012_pilot
    assert not hasattr(args, "output_dir")
    assert not hasattr(args, "raw_cache")


def test_failed_v012_reproduction_rejects_non_quarantine_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifacts, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(
        artifacts,
        "software_provenance",
        lambda: {
            "git_commit": "1" * 40,
            "source_tree_sha256": "2" * 64,
            "uv_lock_sha256": "3" * 64,
        },
    )
    with pytest.raises(ValueError, match="quarantine paths"):
        control_population.reproduce_failed_v012_pilot(
            output_dir=tmp_path / "controls" / "candidate-release",
            raw_cache_path=tmp_path / control_population.FAILED_V012_RAW_CACHE_RELATIVE,
            minimum_joined_rows=55_000,
            generating_command="python -m pharos.cli reproduce_failed_v012_pilot",
        )


def test_failed_v012_reproduction_emits_only_non_authorizing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    joined = _joined_sources(2)
    joined["galactic_l"] = [1.0, 1.0]
    joined["galactic_b"] = [30.0, -30.0]
    strata = [asdict(item) for item in sources.build_sampling_strata(2)]
    cursor = 0
    for item in strata:
        item["collected_rows"] = item["quota"]
        if item["quota"]:
            cursor += item["quota"]
            item["cursor_source_id"] = cursor
    raw_result = sources.SourceQueryResult(
        sources=joined,
        query_text="",
        query_hash="a" * 64,
        n_sources=2,
        gaia_rows=2,
        selection_target_rows=2,
        selection_strata=tuple(strata),
        raw_input_provenance={
            "artifact_sha256": "a" * 64,
            "checkpoint_manifest_sha256": "b" * 64,
            "producer_software": {
                "git_commit": "1" * 40,
                "source_tree_sha256": "2" * 64,
                "uv_lock_sha256": "3" * 64,
            },
            "content_sha256": artifacts.sha256_frame(joined),
        },
    )
    monkeypatch.setattr(artifacts, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(artifacts, "MIN_CONTROL_ROWS", 2)
    monkeypatch.setattr(
        artifacts,
        "software_provenance",
        lambda: dict(raw_result.raw_input_provenance["producer_software"]),
    )
    monkeypatch.setattr(
        sources,
        "fetch_quiet_negative_controls",
        lambda *args, **kwargs: raw_result,
    )
    empty_exclusions = pd.DataFrame(columns=validation.EXCLUSION_COLUMNS)
    monkeypatch.setattr(
        control_population,
        "fetch_simbad_exclusions",
        lambda candidates: (empty_exclusions, []),
    )
    monkeypatch.setattr(
        control_population,
        "fetch_chen_exclusions",
        lambda candidates: (empty_exclusions, []),
    )
    output = tmp_path / control_population.FAILED_V012_OUTPUT_RELATIVE
    result = control_population.reproduce_failed_v012_pilot(
        output_dir=output,
        raw_cache_path=tmp_path / control_population.FAILED_V012_RAW_CACHE_RELATIVE,
        minimum_joined_rows=2,
        generating_command="python -m pharos.cli reproduce_failed_v012_pilot",
    )

    assert result.manifest_path == output / "manifest.yaml"
    assert result.manifest["status"] == "failed"
    assert result.manifest["authorization"] == "non_authorizing"
    with pytest.raises(ValueError, match="unexpected|version/status"):
        artifacts.validate_control_release_candidate(result.manifest_path)


@pytest.mark.parametrize(
    "command",
    ["run_injection_recovery", "run_fdr_report", "run_calibration"],
)
def test_analysis_cli_requires_explicit_release_manifest_and_identity(command: str) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([command])


@pytest.mark.parametrize("command", ["injection", "fdr", "calibration"])
def test_analysis_cli_catches_malformed_release_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (None,))
    output = tmp_path / "must-not-exist"
    if command == "injection":
        result = cli.cmd_run_injection_recovery(
            argparse.Namespace(
                controls_manifest=str(manifest_path),
                controls_release_id="test-authorized-release",
                output_dir=str(output),
                sigmas=["5"],
                threshold=3.0,
                max_pool_size=2,
                seed=0,
            )
        )
    elif command == "fdr":
        result = cli.cmd_run_fdr_report(
            argparse.Namespace(
                controls_manifest=str(manifest_path),
                controls_release_id="test-authorized-release",
                output_dir=str(output),
                q_thresholds=["0.05"],
                seed=0,
            )
        )
    else:
        contaminants = tmp_path / "contaminants.parquet"
        pd.DataFrame({"gaia_dr3_source_id": [1]}).to_parquet(contaminants, index=False)
        preregistration = tmp_path / "preregistration.md"
        preregistration.write_text("test fixture\n", encoding="utf-8")
        result = cli.cmd_run_calibration(
            argparse.Namespace(
                contaminants=str(contaminants),
                controls_manifest=str(manifest_path),
                controls_release_id="test-authorized-release",
                output=str(output / "calibration.yaml"),
                pre_registration=str(preregistration),
                xray_dir=None,
                seed=0,
            )
        )
    assert result == 2
    assert not output.exists()


@pytest.mark.parametrize("command", ["injection", "fdr", "calibration"])
def test_analysis_cli_catches_malformed_raw_checkpoint_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    trusted_release = _trusted_release_for_manifest(manifest_path)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (trusted_release,))
    monkeypatch.setattr(artifacts, "TRUSTED_RAW_CHECKPOINTS", (None,))
    output = tmp_path / "must-not-exist"
    if command == "injection":
        result = cli.cmd_run_injection_recovery(
            argparse.Namespace(
                controls_manifest=str(manifest_path),
                controls_release_id=trusted_release.release_id,
                output_dir=str(output),
                sigmas=["5"],
                threshold=3.0,
                max_pool_size=2,
                seed=0,
            )
        )
    elif command == "fdr":
        result = cli.cmd_run_fdr_report(
            argparse.Namespace(
                controls_manifest=str(manifest_path),
                controls_release_id=trusted_release.release_id,
                output_dir=str(output),
                q_thresholds=["0.05"],
                seed=0,
            )
        )
    else:
        contaminants = tmp_path / "contaminants.parquet"
        pd.DataFrame({"gaia_dr3_source_id": [1]}).to_parquet(contaminants, index=False)
        preregistration = tmp_path / "preregistration.md"
        preregistration.write_text("test fixture\n", encoding="utf-8")
        result = cli.cmd_run_calibration(
            argparse.Namespace(
                contaminants=str(contaminants),
                controls_manifest=str(manifest_path),
                controls_release_id=trusted_release.release_id,
                output=str(output / "calibration.yaml"),
                pre_registration=str(preregistration),
                xray_dir=None,
                seed=0,
            )
        )
    assert result == 2
    assert not output.exists()


def test_calibration_provenance_uses_verified_digest_after_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, controls_path = _valid_manifest(tmp_path, monkeypatch)
    trusted = _trusted_release_for_manifest(manifest_path)
    monkeypatch.setattr(artifacts, "TRUSTED_FINAL_RELEASES", (trusted,))
    authorized = artifacts.load_authorized_control_release(
        manifest_path,
        release_id=trusted.release_id,
    )
    assert authorized.controls_sha256 == trusted.controls.sha256
    assert authorized.controls_descriptor == trusted.controls
    expected_controls = authorized.controls.copy(deep=True)

    contaminants = tmp_path / "contaminants.parquet"
    pd.DataFrame({"gaia_dr3_source_id": [999]}).to_parquet(contaminants, index=False)
    preregistration = tmp_path / "preregistration.md"
    preregistration.write_text("test fixture\n", encoding="utf-8")
    output = tmp_path / "calibration.yaml"

    def replace_after_load(
        contaminant_frame: pd.DataFrame,
        control_frame: pd.DataFrame,
        *,
        random_state: int,
    ) -> calibration.CalibrationResult:
        del contaminant_frame, random_state
        pd.testing.assert_frame_equal(control_frame, expected_controls)
        assert artifacts.sha256_frame(control_frame) == trusted.controls.content_sha256
        controls_path.write_bytes(b"attacker replacement after authorized load")
        return calibration.CalibrationResult(
            betas={"blend": 1.0},
            raw_betas={"blend": 1.0},
            train_loss=0.1,
            train_accuracy=1.0,
            train_auc=1.0,
            score_separation=1.0,
            n_contaminants=1,
            n_controls=len(control_frame),
            fit_metadata={"random_state": 0},
        )

    monkeypatch.setattr(calibration, "calibrate_betas", replace_after_load)
    result = cli.cmd_run_calibration(
        argparse.Namespace(
            contaminants=str(contaminants),
            controls_manifest=str(manifest_path),
            controls_release_id=trusted.release_id,
            output=str(output),
            pre_registration=str(preregistration),
            xray_dir=None,
            seed=0,
        )
    )
    assert result == 0
    assert artifacts.sha256_file(controls_path) != trusted.controls.sha256
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert payload["input_fixtures"]["controls"] == {
        "path": str(controls_path),
        "sha256": trusted.controls.sha256,
    }


def test_release_loader_rejects_incomplete_simbad_trace_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    simbad_indexes = [
        index
        for index, trace in enumerate(payload["query_provenance"])
        if trace["service"] == "SIMBAD"
    ]
    del payload["query_provenance"][simbad_indexes[0]]
    artifacts.atomic_write_yaml(payload, manifest_path)
    with pytest.raises(ValueError, match="bind Gaia|count/order"):
        artifacts.validate_control_release_candidate(manifest_path)


def test_failed_pilot_release_producer_is_rejected_by_later_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["software"] = {
        "git_commit": "619dc557f2b0782f7f92dbc6ebcdc67413667020",
        "source_tree_sha256": (
            "acf8a344821151788e596dd4e31038c3b80501a92b969502fc795e3f04936a62"
        ),
        "uv_lock_sha256": (
            "a5947dc7f96f67447ab0a2d5d412b22aa4f3ff65765819518a359dcb731bf731"
        ),
    }
    artifacts.atomic_write_yaml(payload, manifest_path)
    later_runtime = {
        "git_commit": "9" * 40,
        "source_tree_sha256": "8" * 64,
        "uv_lock_sha256": "7" * 64,
    }
    monkeypatch.setattr(artifacts, "software_provenance", lambda: later_runtime)
    with pytest.raises(ValueError, match="software provenance"):
        artifacts.validate_control_release_candidate(manifest_path)


@pytest.mark.parametrize("command", ["injection", "fdr", "calibration"])
def test_failed_pilot_release_cannot_enter_analysis_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    def forbid_review_loader(*args: object, **kwargs: object) -> pd.DataFrame:
        raise AssertionError("analysis command called the review-only candidate API")

    monkeypatch.setattr(
        artifacts,
        "validate_control_release_candidate",
        forbid_review_loader,
    )
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["software"] = {
        "git_commit": "619dc557f2b0782f7f92dbc6ebcdc67413667020",
        "source_tree_sha256": (
            "acf8a344821151788e596dd4e31038c3b80501a92b969502fc795e3f04936a62"
        ),
        "uv_lock_sha256": (
            "a5947dc7f96f67447ab0a2d5d412b22aa4f3ff65765819518a359dcb731bf731"
        ),
    }
    artifacts.atomic_write_yaml(payload, manifest_path)
    monkeypatch.setattr(
        artifacts,
        "software_provenance",
        lambda: {
            "git_commit": "9" * 40,
            "source_tree_sha256": "8" * 64,
            "uv_lock_sha256": "7" * 64,
        },
    )
    output = tmp_path / "must-not-exist"
    if command == "injection":
        args = argparse.Namespace(
            controls_manifest=str(manifest_path),
            controls_release_id="failed-v0.1.2",
            output_dir=str(output),
            sigmas=["5"],
            threshold=3.0,
            max_pool_size=2,
            seed=0,
        )
        result = cli.cmd_run_injection_recovery(args)
    elif command == "fdr":
        args = argparse.Namespace(
            controls_manifest=str(manifest_path),
            controls_release_id="failed-v0.1.2",
            output_dir=str(output),
            q_thresholds=["0.05"],
            seed=0,
        )
        result = cli.cmd_run_fdr_report(args)
    else:
        contaminants = tmp_path / "contaminants.parquet"
        pd.DataFrame({"gaia_dr3_source_id": [1]}).to_parquet(contaminants, index=False)
        preregistration = tmp_path / "preregistration.md"
        preregistration.write_text("frozen test fixture\n", encoding="utf-8")
        args = argparse.Namespace(
            contaminants=str(contaminants),
            controls_manifest=str(manifest_path),
            controls_release_id="failed-v0.1.2",
            output=str(output / "calibration.yaml"),
            pre_registration=str(preregistration),
            xray_dir=None,
            seed=0,
        )
        result = cli.cmd_run_calibration(args)
    assert result == 2
    assert not output.exists()


def test_manifest_rejects_forged_stratum_quota_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["selection"]["strata"][0]["quota"] = 2
    payload["selection"]["strata"][0]["collected_rows"] = 2
    payload["selection"]["strata"][1]["quota"] = 0
    payload["selection"]["strata"][1]["collected_rows"] = 0
    with pytest.raises(ValueError, match="deterministic allocation"):
        artifacts.validate_control_manifest(payload)


def test_stratified_query_binds_cursor_bounds_and_teff_eligibility() -> None:
    stratum = sources.build_sampling_strata(24)[7]
    query = sources.build_quiet_negative_joined_adql(1, after_source_id=123, stratum=stratum)
    assert "gs.source_id > 123" in query
    assert "gs.teff_gspphot IS NOT NULL" in query
    assert f"gs.l >= {stratum.longitude_min_deg:.1f}" in query
    assert f"gs.l < {stratum.longitude_max_deg:.1f}" in query
    assert ("gs.b > 20.0" if stratum.hemisphere == "north" else "gs.b < -20.0") in query


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("teff_gspphot", float("nan"), "teff"),
        ("teff_gspphot", 1e308, "temperature"),
        ("wise_xm_n_neighbours", 2, "multiplicity"),
        ("w3snr", 2.99, "W3 SNR"),
        ("w1mpro_error", -0.1, "W1 uncertainty"),
        ("w1mpro_error", 0.0, "W1 uncertainty"),
        ("w2mpro_error", 0.0, "W2 uncertainty"),
        ("w3mpro_error", 0.0, "W3 uncertainty"),
        ("w4mpro", float("nan"), "partial W4"),
        ("w4mpro_error", 0.0, "W4 uncertainty"),
        ("w4snr", -0.1, "W4 SNR"),
        ("tmass_ks_msigcom", -0.1, "Ks uncertainty"),
        ("tmass_xm_angular_distance", 1.6, "outside"),
    ],
)
def test_loader_gate_revalidation_rejects_registered_cut_bypass(
    column: str, value: object, message: str
) -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    controls.loc[0, column] = value
    with pytest.raises((TypeError, ValueError), match=message):
        validation.validate_control_artifact(controls, minimum_rows=2)


@pytest.mark.parametrize(("band", "minimum_snr"), [("w1", 5.0), ("w2", 5.0), ("w3", 3.0)])
def test_wise_registered_snr_boundary_is_accepted(band: str, minimum_snr: float) -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    controls[f"{band}mpro_error"] = validation.WISE_MAG_ERROR_TO_SNR / minimum_snr
    controls[f"{band}snr"] = minimum_snr
    validation.validate_control_artifact(controls, minimum_rows=2)


@pytest.mark.parametrize(("band", "minimum_snr"), [("w1", 5.0), ("w2", 5.0), ("w3", 3.0)])
def test_wise_error_above_registered_boundary_is_rejected(
    band: str, minimum_snr: float
) -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    maximum = validation.WISE_MAG_ERROR_TO_SNR / minimum_snr
    controls[f"{band}mpro_error"] = maximum + 1e-6
    controls[f"{band}snr"] = validation.WISE_MAG_ERROR_TO_SNR / (maximum + 1e-6)
    with pytest.raises(ValueError, match=f"{band.upper()} uncertainty"):
        validation.validate_control_artifact(controls, minimum_rows=2)


def test_wise_forged_stored_snr_is_rejected() -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    controls.loc[0, "w2snr"] += 0.01
    with pytest.raises(ValueError, match="W2 SNR is inconsistent"):
        validation.validate_control_artifact(controls, minimum_rows=2)


def test_optional_w4_boundary_and_subthreshold_normalization() -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    boundary_error = validation.WISE_MAG_ERROR_TO_SNR / 2.0
    controls["w4mpro_error"] = boundary_error
    controls["w4snr"] = 2.0
    validation.validate_control_artifact(controls, minimum_rows=2)

    subthreshold = controls.loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    subthreshold["w4mpro_error"] = validation.WISE_MAG_ERROR_TO_SNR
    subthreshold["w4snr"] = 1.0
    normalized = validation.normalize_optional_w4(subthreshold)
    assert normalized[["w4mpro", "w4mpro_error", "w4snr"]].isna().all().all()
    validation.validate_joined_source_frame(normalized, maximum_rows=2)


@pytest.mark.parametrize(
    ("w4mpro", "w4mpro_error", "w4snr"),
    [
        (10.0, float("nan"), float("nan")),  # magnitude only
        (float("nan"), 0.3, float("nan")),  # uncertainty only
        (float("nan"), float("nan"), 3.619),  # SNR only
        (10.0, 0.3, float("nan")),  # magnitude + uncertainty, no derived SNR
        (10.0, float("nan"), 3.619),  # magnitude + SNR
        (float("nan"), 0.3, 3.619),  # uncertainty + SNR
    ],
)
def test_optional_w4_response_partial_patterns_become_wholly_absent(
    w4mpro: float, w4mpro_error: float, w4snr: float
) -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    response.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]] = [
        w4mpro,
        w4mpro_error,
        w4snr,
    ]
    original = response.copy(deep=True)

    normalized = validation.normalize_optional_w4(response)

    pd.testing.assert_frame_equal(response, original)
    assert normalized.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]].isna().all()
    validation.validate_joined_source_frame(normalized, maximum_rows=1)


@pytest.mark.parametrize(
    ("w4mpro", "w4mpro_error", "w4snr", "error_type", "message"),
    [
        (float("inf"), float("nan"), float("nan"), ValueError, "must be finite"),
        ("not-a-number", float("nan"), float("nan"), TypeError, "must be numeric"),
        (float("nan"), -0.1, float("nan"), ValueError, "uncertainty must be positive"),
        (float("nan"), float("nan"), -0.1, ValueError, "SNR must be non-negative"),
        (float("nan"), 0.3, 99.0, ValueError, "SNR is inconsistent"),
    ],
)
def test_optional_w4_response_malformed_partial_patterns_are_rejected(
    w4mpro: object,
    w4mpro_error: float,
    w4snr: float,
    error_type: type[Exception],
    message: str,
) -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    if isinstance(w4mpro, str):
        response["w4mpro"] = response["w4mpro"].astype(object)
    response.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]] = [
        w4mpro,
        w4mpro_error,
        w4snr,
    ]

    with pytest.raises(error_type, match=message):
        validation.normalize_optional_w4(response)


@pytest.mark.parametrize("error", [0.0, -0.1])
def test_optional_w4_response_complete_nonpositive_error_is_rejected(error: float) -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    response.loc[0, "w4mpro_error"] = error
    response.loc[0, "w4snr"] = validation.WISE_MAG_ERROR_TO_SNR / error if error else float("inf")

    with pytest.raises(ValueError, match="uncertainty must be positive"):
        validation.normalize_optional_w4(response)


def test_optional_w4_response_valid_complete_triple_is_preserved() -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    original = response.copy(deep=True)
    expected = response.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]].copy()

    normalized = validation.normalize_optional_w4(response)

    pd.testing.assert_frame_equal(response, original)
    pd.testing.assert_series_equal(
        normalized.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]], expected
    )
    validation.validate_joined_source_frame(normalized, maximum_rows=1)


def test_optional_w4_response_wholly_absent_remains_wholly_absent() -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    response.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]] = float("nan")

    normalized = validation.normalize_optional_w4(response)

    assert normalized.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]].isna().all()
    validation.validate_joined_source_frame(normalized, maximum_rows=1)


@pytest.mark.parametrize(
    ("column", "value", "error_type", "message"),
    [
        ("w4mpro", float("inf"), ValueError, "must be finite"),
        ("w4mpro_error", float("inf"), ValueError, "must be finite"),
        ("w4snr", float("inf"), ValueError, "must be finite"),
        ("w4snr", 999.0, ValueError, "SNR is inconsistent"),
        ("w4mpro", "not-a-number", TypeError, "must be numeric"),
    ],
)
def test_optional_w4_response_complete_malformed_triple_is_rejected(
    column: str,
    value: object,
    error_type: type[Exception],
    message: str,
) -> None:
    response = _joined_sources(1).loc[:, validation.JOINED_SOURCE_COLUMNS].copy()
    if isinstance(value, str):
        response[column] = response[column].astype(object)
    response.loc[0, column] = value

    with pytest.raises(error_type, match=message):
        validation.normalize_optional_w4(response)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("w4mpro", float("nan"), "partial W4"),
        ("w4mpro_error", float("nan"), "partial W4"),
        ("w4snr", float("nan"), "partial W4"),
        ("w4mpro_error", 0.0, "W4 uncertainty"),
        ("w4mpro_error", -0.1, "W4 uncertainty"),
        ("w4snr", 999.0, "W4 SNR is inconsistent"),
    ],
)
def test_artifact_loader_boundary_rejects_partial_or_forged_w4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    value: float,
    message: str,
) -> None:
    manifest_path, controls_path = _valid_manifest(tmp_path, monkeypatch)
    artifact = pd.read_parquet(controls_path)
    artifact.loc[0, column] = value
    forged_path = artifacts.write_content_addressed_parquet(
        artifact, directory=tmp_path, prefix="quiet_negative_bad_w4"
    )
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"]["controls"] = {
        "path": forged_path.name,
        "sha256": artifacts.sha256_file(forged_path),
        "row_count": len(artifact),
        "columns": list(artifact.columns),
        "schema_version": artifacts.CONTROL_SCHEMA_VERSION,
    }
    artifacts.atomic_write_yaml(payload, manifest_path)

    with pytest.raises(ValueError, match=message):
        artifacts.validate_control_release_candidate(manifest_path)


def test_bp_rp_relational_revalidation_rejects_forged_delta() -> None:
    controls = control_population.apply_bp_rp_excess_cut(_joined_sources(2))
    controls.loc[0, "bp_rp_excess_delta"] = 0.01
    with pytest.raises(ValueError, match="residual relationship"):
        validation.validate_control_artifact(controls, minimum_rows=2)


def test_loader_recomputes_bp_rp_medians_from_bound_parent_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, controls_path = _valid_manifest(tmp_path, monkeypatch)
    forged = pd.read_parquet(controls_path)
    forged["bp_rp_excess_bin_median"] += 0.05
    forged["bp_rp_excess_delta"] = (
        forged["phot_bp_rp_excess_factor"] - forged["bp_rp_excess_bin_median"]
    )
    forged_path = artifacts.write_content_addressed_parquet(
        forged, directory=tmp_path, prefix="quiet_negative_forged"
    )
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"]["controls"] = {
        "path": forged_path.name,
        "sha256": artifacts.sha256_file(forged_path),
        "row_count": len(forged),
        "columns": list(forged.columns),
        "schema_version": artifacts.CONTROL_SCHEMA_VERSION,
    }
    artifacts.atomic_write_yaml(payload, manifest_path)
    with pytest.raises(ValueError, match="parent-population derivation"):
        artifacts.validate_control_release_candidate(manifest_path)


def test_release_manifest_separately_binds_historical_raw_and_release_producers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    release_producer = dict(payload["software"])
    historical = {
        "git_commit": "4" * 40,
        "source_tree_sha256": "5" * 64,
        "uv_lock_sha256": "6" * 64,
    }
    payload["raw_input_provenance"]["producer_software"] = historical
    trusted = artifacts.TrustedRawCheckpoint(
        git_commit=historical["git_commit"],
        source_tree_sha256=historical["source_tree_sha256"],
        uv_lock_sha256=historical["uv_lock_sha256"],
        artifact_sha256=payload["raw_input_provenance"]["artifact_sha256"],
        manifest_sha256=payload["raw_input_provenance"]["checkpoint_manifest_sha256"],
        content_sha256=payload["raw_input_provenance"]["content_sha256"],
        row_count=payload["artifacts"]["raw_candidates"]["row_count"],
    )
    monkeypatch.setattr(artifacts, "TRUSTED_RAW_CHECKPOINTS", (trusted,))

    validated = artifacts.validate_control_manifest(payload)

    assert dict(validated["software"]) == release_producer
    assert dict(validated["raw_input_provenance"]["producer_software"]) != release_producer
    assert (
        validated["raw_input_provenance"]["artifact_sha256"]
        == payload["raw_input_provenance"]["artifact_sha256"]
    )

    forged = copy.deepcopy(payload)
    forged["raw_input_provenance"]["producer_software"]["git_commit"] = "0" * 40
    with pytest.raises(ValueError, match="raw input provenance"):
        artifacts.validate_control_manifest(forged)


@pytest.mark.parametrize(
    "field",
    [
        "artifact_sha256",
        "checkpoint_manifest_sha256",
        "content_sha256",
        "released_artifact_sha256",
    ],
)
def test_release_manifest_rejects_arbitrary_raw_provenance_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["raw_input_provenance"][field] = "7" * 64
    with pytest.raises(ValueError, match="raw input provenance"):
        artifacts.validate_control_manifest(payload)


def test_exact_exclusion_dedup_then_residual_duplicate_rejection() -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-1",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 1.0,
        "catalog_release": validation.SIMBAD_EXCLUSION_RELEASE,
    }
    duplicated = pd.DataFrame([row, row], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match="exact duplicate"):
        validation.validate_exclusions(duplicated)
    normalized = control_population.normalize_exclusions(duplicated)
    assert len(normalized) == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("matched_object_id", "", "must be non-empty"),
        ("matched_otype", "Star", "object type is not registered"),
        ("exclusion_class", "YSO", "type/class mapping mismatch"),
        ("catalog_release", "SIMBAD forged release", "catalog release mismatch"),
    ],
)
def test_simbad_exclusion_rejects_empty_relabeled_and_forged_fields(
    field: str,
    value: str,
    message: str,
) -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-1",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 1.0,
        "catalog_release": validation.SIMBAD_EXCLUSION_RELEASE,
    }
    row[field] = value
    frame = pd.DataFrame([row], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match=message):
        validation.validate_exclusions(frame)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("exclusion_class", "AGN", "Chen exclusion class mismatch"),
        ("matched_otype", "disk", "Chen object type mismatch"),
        ("catalog_release", "Chen latest", "Chen catalog release mismatch"),
    ],
)
def test_chen_exclusion_requires_exact_type_and_release(
    field: str,
    value: str,
    message: str,
) -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "Chen2014",
        "exclusion_class": "debris_disk",
        "matched_object_id": "HD 1",
        "matched_otype": "debris_disk",
        "angular_distance_arcsec": 1.0,
        "catalog_release": validation.CHEN_EXCLUSION_RELEASE,
    }
    row[field] = value
    frame = pd.DataFrame([row], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match=message):
        validation.validate_exclusions(frame)


def test_exclusion_rejects_duplicate_catalog_identity_with_changed_distance() -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-1",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 1.0,
        "catalog_release": validation.SIMBAD_EXCLUSION_RELEASE,
    }
    duplicate_identity = {**row, "angular_distance_arcsec": 2.0}
    frame = pd.DataFrame([row, duplicate_identity], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match="duplicate catalog object identity"):
        validation.validate_exclusions(frame)


def test_exclusion_normalization_preserves_distinct_object_types_and_is_deterministic() -> None:
    base = {
        "gaia_dr3_source_id": 7,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-7",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 2.0,
        "catalog_release": "SIMBAD live database",
    }
    conflict = {**base, "matched_otype": "QSO"}
    other = {**base, "gaia_dr3_source_id": 3, "matched_object_id": "AGN-3"}
    first = pd.DataFrame([conflict, other, base, base], columns=validation.EXCLUSION_COLUMNS)
    second = first.iloc[[3, 1, 0, 2]].reset_index(drop=True)

    normalized_first = control_population.normalize_exclusions(first)
    normalized_second = control_population.normalize_exclusions(second)

    pd.testing.assert_frame_equal(normalized_first, normalized_second)
    assert len(normalized_first) == 3
    assert normalized_first.loc[
        normalized_first["gaia_dr3_source_id"] == 7, "matched_otype"
    ].tolist() == ["AGN", "QSO"]


def test_simbad_live_duplicate_shape_preserves_response_provenance_and_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astropy.table import Table
    from astroquery.simbad import Simbad

    response = pd.DataFrame(
        [
            (2, "YSO-2", "Y*O", 3.0),
            (1, "AGN-1", "AGN", 1.0),
            (1, "AGN-1", "AGN", 1.0),
            (1, "AGN-1", "QSO", 1.0),
        ],
        columns=validation.SIMBAD_RESPONSE_COLUMNS,
    )
    response["gaia_dr3_source_id"] = response["gaia_dr3_source_id"].astype("int64")

    def fake_query_tap(*args: object, **kwargs: object) -> Table:
        return Table.from_pandas(response)

    monkeypatch.setattr(Simbad, "query_tap", fake_query_tap)
    candidates = _joined_sources(3).loc[:, ["gaia_dr3_source_id", "ra", "dec"]]

    exclusions, traces = control_population.fetch_simbad_exclusions(candidates)

    assert len(traces) == 1
    assert traces[0].response_rows == 4
    assert traces[0].response_sha256 == artifacts.sha256_frame(response)
    assert len(exclusions) == 3
    assert exclusions["gaia_dr3_source_id"].tolist() == [1, 1, 2]
    assert exclusions.loc[exclusions["gaia_dr3_source_id"] == 1, "matched_otype"].tolist() == [
        "AGN",
        "QSO",
    ]

    remaining = control_population.apply_external_exclusions(_joined_sources(3), exclusions)
    assert remaining["gaia_dr3_source_id"].tolist() == [3]


def test_exclusion_materialization_bound_precedes_deduplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-1",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 1.0,
        "catalog_release": "test",
    }
    monkeypatch.setattr(validation, "MAX_EXCLUSION_ROWS", 1)
    duplicated = pd.DataFrame([row, row], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match="materialization bound"):
        control_population.normalize_exclusions(duplicated)


def test_content_addressed_publication_refuses_existing_generation(tmp_path: Path) -> None:
    frame = _joined_sources(1)
    path = artifacts.write_content_addressed_parquet(
        frame, directory=tmp_path, prefix="quiet_negative"
    )
    assert path.name == f"quiet_negative.{artifacts.sha256_file(path)}.parquet"
    with pytest.raises(FileExistsError, match="conflicting"):
        artifacts.write_content_addressed_parquet(
            frame, directory=tmp_path, prefix="quiet_negative"
        )


def test_release_directory_publication_refuses_raced_empty_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / ".release.staging"
    staging.mkdir()
    (staging / "payload.parquet").write_bytes(b"payload")
    (staging / "manifest.yaml").write_text("status: validated\n", encoding="utf-8")
    output = tmp_path / "release"
    real_mkdir = artifacts.os.mkdir

    def race_mkdir(path: object, mode: int = 0o777) -> None:
        if Path(path) == output and not output.exists():
            real_mkdir(path, mode)
        real_mkdir(path, mode)

    monkeypatch.setattr(artifacts.os, "mkdir", race_mkdir)
    with pytest.raises(FileExistsError, match="conflicting final release"):
        artifacts.install_release_directory_no_replace(staging, output)
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert (staging / "manifest.yaml").is_file()


def test_release_manifest_is_linked_only_after_payload_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / ".release.staging"
    staging.mkdir()
    (staging / "payload.parquet").write_bytes(b"payload")
    (staging / "manifest.yaml").write_text("status: validated\n", encoding="utf-8")
    output = tmp_path / "release"
    real_link = artifacts.os.link
    events: list[str] = []

    def recording_link(source: object, destination: object, **kwargs: object) -> None:
        events.append(f"link:{Path(source).name}")
        real_link(source, destination, **kwargs)

    def recording_fsync(path: Path) -> None:
        events.append(f"fsync:{path.name}")

    monkeypatch.setattr(artifacts.os, "link", recording_link)
    monkeypatch.setattr(artifacts, "_fsync_directory", recording_fsync)
    artifacts.install_release_directory_no_replace(staging, output)
    assert events[:4] == [
        "link:payload.parquet",
        "fsync:release",
        "link:manifest.yaml",
        "fsync:release",
    ]


def test_loader_rejects_symlink_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, controls_path = _valid_manifest(tmp_path, monkeypatch)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.parquet"
    outside.write_bytes(controls_path.read_bytes())
    controls_path.unlink()
    controls_path.symlink_to(outside)
    try:
        with pytest.raises(ValueError, match="symlink"):
            artifacts.validate_control_release_candidate(manifest_path)
    finally:
        outside.unlink(missing_ok=True)


def test_yaml_size_and_aliases_fail_before_safe_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = tmp_path / "oversized.yaml"
    oversized.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setattr(artifacts, "MAX_YAML_BYTES", 8)
    with pytest.raises(ValueError, match="byte bound"):
        artifacts._read_bounded_yaml_with_sha256(oversized, root=tmp_path)  # noqa: SLF001

    monkeypatch.setattr(artifacts, "MAX_YAML_BYTES", 1024)
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text("base: &base [1]\ncopy: *base\n", encoding="utf-8")
    with pytest.raises(ValueError, match="aliases and anchors"):
        artifacts._read_bounded_yaml(aliases, root=tmp_path)  # noqa: SLF001


def test_yaml_symlink_swap_is_refused_at_single_descriptor_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.yaml"
    outside = tmp_path / "outside.yaml"
    manifest.write_text("status: validated\n", encoding="utf-8")
    outside.write_text("status: forged\n", encoding="utf-8")
    real_open = artifacts.os.open
    swapped = False

    def swap_then_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if Path(path) == manifest and not swapped:
            swapped = True
            manifest.unlink()
            manifest.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "open", swap_then_open)
    with pytest.raises(ValueError, match="without following symlinks"):
        artifacts._read_bounded_yaml_with_sha256(manifest, root=tmp_path)  # noqa: SLF001


def test_bounded_yaml_hash_covers_exact_parsed_descriptor_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    raw = b"status: validated\n"
    manifest.write_bytes(raw)
    payload, digest = artifacts._read_bounded_yaml_with_sha256(  # noqa: SLF001
        manifest, root=tmp_path
    )
    assert payload == {"status": "validated"}
    assert digest == hashlib.sha256(raw).hexdigest()


def test_verified_parquet_accepts_symlinked_ancestor_alias(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    release = real_parent / "release"
    release.mkdir(parents=True)
    frame = _joined_sources(1)
    path = release / "rows.parquet"
    frame.to_parquet(path, index=False)
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    alias_root = alias_parent / "release"
    descriptor = {
        "sha256": artifacts.sha256_file(path),
        "row_count": len(frame),
        "columns": list(frame.columns),
    }
    loaded = artifacts._read_verified_parquet(  # noqa: SLF001
        path.resolve(),
        root=alias_root,
        maximum_rows=1,
        descriptor=descriptor,
    )
    pd.testing.assert_frame_equal(loaded, frame)


def test_parquet_row_bound_is_checked_from_metadata(tmp_path: Path) -> None:
    path = tmp_path / "rows.parquet"
    frame = _joined_sources(2)
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="row bound"):
        artifacts._preflight_parquet(  # noqa: SLF001
            path,
            root=tmp_path,
            maximum_rows=1,
            expected_rows=2,
            expected_columns=list(frame.columns),
        )


def test_parquet_byte_bound_is_checked_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bytes.parquet"
    frame = _joined_sources(1)
    frame.to_parquet(path, index=False)
    monkeypatch.setattr(artifacts, "MAX_PARQUET_BYTES", path.stat().st_size - 1)
    with pytest.raises(ValueError, match="byte bound"):
        artifacts._preflight_parquet(  # noqa: SLF001
            path,
            root=tmp_path,
            maximum_rows=1,
            expected_rows=1,
            expected_columns=list(frame.columns),
        )


def test_manifest_rejects_provenance_substitution_and_relational_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    path_escape = copy.deepcopy(payload)
    path_escape["artifacts"]["controls"]["path"] = "../escape.parquet"
    with pytest.raises(ValueError, match="escape"):
        artifacts.validate_control_manifest(path_escape)

    endpoint_swap = copy.deepcopy(payload)
    endpoint_swap["query_provenance"][0]["endpoint"] = artifacts.SIMBAD_ENDPOINT
    with pytest.raises(ValueError, match="endpoint mismatch"):
        artifacts.validate_control_manifest(endpoint_swap)

    count_swap = copy.deepcopy(payload)
    count_swap["filter_counts"]["final_rows"] += 1
    with pytest.raises(ValueError, match="relational"):
        artifacts.validate_control_manifest(count_swap)

    for field, replacement in (
        ("git_commit", "0" * 40),
        ("source_tree_sha256", "0" * 64),
        ("uv_lock_sha256", "0" * 64),
    ):
        software_swap = copy.deepcopy(payload)
        software_swap["software"][field] = replacement
        artifacts.atomic_write_yaml(software_swap, manifest_path)
        with pytest.raises(ValueError, match="software provenance"):
            artifacts.validate_control_release_candidate(manifest_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("simbad_input", "SIMBAD provenance input"),
        ("simbad_raw_count", "raw/normalized response counts"),
        ("chen_query", "Chen provenance query/input"),
        ("duplicate_simbad", "reordered|count/order"),
    ],
)
def test_loader_rejects_forged_external_trace_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    simbad_index = next(
        index
        for index, trace in enumerate(payload["query_provenance"])
        if trace["service"] == "SIMBAD"
    )
    chen_index = next(
        index
        for index, trace in enumerate(payload["query_provenance"])
        if trace["service"] == "VizieR Chen2014"
    )
    if mutation == "simbad_input":
        payload["query_provenance"][simbad_index]["input_sha256"] = "a" * 64
    elif mutation == "simbad_raw_count":
        payload["query_provenance"][simbad_index]["response_rows"] = 1
    elif mutation == "chen_query":
        payload["query_provenance"][chen_index]["query_sha256"] = "b" * 64
    else:
        payload["query_provenance"].insert(
            chen_index, copy.deepcopy(payload["query_provenance"][simbad_index])
        )
    artifacts.atomic_write_yaml(payload, manifest_path)
    with pytest.raises(ValueError, match=message):
        artifacts.validate_control_release_candidate(manifest_path)

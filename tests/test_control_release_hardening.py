"""Regression tests for hardened control acquisition and publication boundaries."""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from pharos import artifacts, control_population, sources, validation
from tests.test_control_population import _joined_sources, _valid_manifest


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
        artifacts.load_control_artifact(manifest_path)


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
        artifacts.load_control_artifact(manifest_path)


def test_exact_exclusion_dedup_then_residual_duplicate_rejection() -> None:
    row = {
        "gaia_dr3_source_id": 1,
        "exclusion_catalog": "SIMBAD",
        "exclusion_class": "AGN",
        "matched_object_id": "AGN-1",
        "matched_otype": "AGN",
        "angular_distance_arcsec": 1.0,
        "catalog_release": "test",
    }
    duplicated = pd.DataFrame([row, row], columns=validation.EXCLUSION_COLUMNS)
    with pytest.raises(ValueError, match="exact duplicate"):
        validation.validate_exclusions(duplicated)
    normalized = control_population.normalize_exclusions(duplicated)
    assert len(normalized) == 1


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
            artifacts.load_control_artifact(manifest_path)
    finally:
        outside.unlink(missing_ok=True)


def test_yaml_size_and_aliases_fail_before_safe_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = tmp_path / "oversized.yaml"
    oversized.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setattr(artifacts, "MAX_YAML_BYTES", 8)
    with pytest.raises(ValueError, match="byte bound"):
        artifacts._read_bounded_yaml(oversized, root=tmp_path)  # noqa: SLF001

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
        artifacts._read_bounded_yaml(manifest, root=tmp_path)  # noqa: SLF001


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
            artifacts.load_control_artifact(manifest_path)

"""Adversarial tests for the v0.1.2 control-population trust boundary."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pharos import artifacts, cli, control_population, sources, validation


def _joined_sources(n_rows: int = 3) -> pd.DataFrame:
    row = {
        "gaia_dr3_source_id": 1,
        "ra": 10.0,
        "dec": 20.0,
        "galactic_l": 100.0,
        "galactic_b": 30.0,
        "parallax": 10.0,
        "parallax_error": 1.0,
        "parallax_over_error": 10.0,
        "pmra": 0.0,
        "pmdec": 0.0,
        "ruwe": 1.0,
        "astrometric_excess_noise": 0.0,
        "astrometric_excess_noise_sig": 0.0,
        "phot_g_mean_mag": 10.0,
        "phot_bp_rp_excess_factor": 1.2,
        "ipd_frac_multi_peak": 0,
        "ipd_frac_odd_win": 0,
        "duplicated_source": False,
        "non_single_star": 0,
        "qso_probability": 0.01,
        "galaxy_probability": 0.01,
        "teff_gspphot": 5000.0,
        "logg_gspphot": 4.5,
        "distance_gspphot": 100.0,
        "ag_gspphot": 0.0,
        "wise_xm_angular_distance": 0.1,
        "wise_xm_n_neighbours": 1,
        "wise_xm_n_mates": 0,
        "wise_xm_flag": 8,
        "allwise_designation": "J000000+000000",
        "w1mpro": 10.0,
        "w1mpro_error": 0.1,
        "w1snr": 10.857,
        "w2mpro": 10.0,
        "w2mpro_error": 0.1,
        "w2snr": 10.857,
        "w3mpro": 10.0,
        "w3mpro_error": 0.2,
        "w3snr": 5.4285,
        "w4mpro": 10.0,
        "w4mpro_error": 0.3,
        "w4snr": 3.619,
        "allwise_cc_flags": "0000",
        "allwise_ext_flg": 0,
        "tmass_xm_angular_distance": 0.1,
        "tmass_designation": "00000000+0000000",
        "tmass_j_m": 10.5,
        "tmass_j_msigcom": 0.03,
        "tmass_h_m": 10.2,
        "tmass_h_msigcom": 0.03,
        "tmass_ks_m": 10.1,
        "tmass_ks_msigcom": 0.03,
    }
    frame = pd.DataFrame([row for _ in range(n_rows)], columns=validation.JOINED_SOURCE_COLUMNS)
    frame["gaia_dr3_source_id"] = np.arange(1, n_rows + 1, dtype=np.int64)
    frame["ra"] = np.linspace(10.0, 11.0, n_rows)
    frame["phot_g_mean_mag"] = np.linspace(10.0, 10.4, n_rows)
    frame["allwise_designation"] = [f"WISE-{index}" for index in range(n_rows)]
    frame["tmass_designation"] = [f"2MASS-{index}" for index in range(n_rows)]
    return frame


def _valid_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    monkeypatch.setattr(artifacts, "MIN_CONTROL_ROWS", 2)
    joined = _joined_sources(2)
    joined["galactic_l"] = [1.0, 1.0]
    joined["galactic_b"] = [30.0, -30.0]
    controls = control_population.apply_bp_rp_excess_cut(joined)
    exclusions = pd.DataFrame(columns=validation.EXCLUSION_COLUMNS)
    raw_candidates_path = artifacts.write_content_addressed_parquet(
        joined, directory=tmp_path, prefix="raw_candidates"
    )
    controls_path = artifacts.write_content_addressed_parquet(
        controls, directory=tmp_path, prefix="quiet_negative"
    )
    exclusions_path = artifacts.write_content_addressed_parquet(
        exclusions, directory=tmp_path, prefix="exclusions"
    )
    manifest_path = tmp_path / "manifest.yaml"
    query_hash = hashlib.sha256(b"query").hexdigest()
    strata = [asdict(item) for item in sources.build_sampling_strata(2)]
    cursor = 0
    for item in strata:
        item["collected_rows"] = item["quota"]
        if item["quota"]:
            cursor += item["quota"]
            item["cursor_source_id"] = cursor
    manifest = artifacts.build_control_manifest(
        raw_candidates_path=raw_candidates_path,
        raw_candidates=joined,
        control_path=controls_path,
        controls=controls,
        exclusions_path=exclusions_path,
        exclusions=exclusions,
        retrieved_at_utc="2026-08-05T20:00:00Z",
        generating_command="python -m pharos.cli build_quiet_negative_v012",
        query_provenance=[
            {
                "service": "Gaia TAP joined",
                "endpoint": artifacts.GAIA_ENDPOINT,
                "query_sha256": query_hash,
                "input_sha256": query_hash,
                "response_sha256": query_hash,
                "response_rows": 2,
                "requested_at_utc": "2026-08-05T19:59:00Z",
                "received_at_utc": "2026-08-05T20:00:00Z",
            },
            {
                "service": "SIMBAD",
                "endpoint": artifacts.SIMBAD_ENDPOINT,
                "query_sha256": query_hash,
                "input_sha256": query_hash,
                "response_sha256": query_hash,
                "response_rows": 0,
                "requested_at_utc": "2026-08-05T20:00:00Z",
                "received_at_utc": "2026-08-05T20:00:01Z",
            },
            {
                "service": "VizieR Chen2014",
                "endpoint": artifacts.VIZIER_ENDPOINT,
                "query_sha256": query_hash,
                "input_sha256": query_hash,
                "response_sha256": query_hash,
                "response_rows": 0,
                "requested_at_utc": "2026-08-05T20:00:01Z",
                "received_at_utc": "2026-08-05T20:00:02Z",
            },
        ],
        filter_counts={
            "gaia_rows": 2,
            "joined_rows": 2,
            "after_bp_rp_rows": 2,
            "simbad_excluded_sources": 0,
            "chen_excluded_sources": 0,
            "excluded_unique_sources": 0,
            "final_rows": 2,
        },
        selection_target_rows=2,
        selection_strata=strata,
    )
    artifacts.atomic_write_yaml(manifest, manifest_path)
    return manifest_path, controls_path


def test_bp_rp_cut_is_magnitude_binned_and_preserves_exact_schema() -> None:
    frame = _joined_sources(4)
    frame["phot_g_mean_mag"] = [10.0, 10.1, 11.0, 11.1]
    frame["phot_bp_rp_excess_factor"] = [1.0, 1.05, 1.0, 1.5]
    result = control_population.apply_bp_rp_excess_cut(frame)
    assert result["gaia_dr3_source_id"].tolist() == [1, 2]
    assert tuple(result.columns) == validation.CONTROL_ARTIFACT_COLUMNS
    assert result["bp_rp_excess_delta"].abs().max() <= 0.1


def test_remote_schema_rejects_extra_column() -> None:
    gaia = _joined_sources(1).loc[:, validation.GAIA_RESPONSE_COLUMNS].copy()
    gaia["attacker_controlled"] = "payload"
    with pytest.raises(ValueError, match="schema mismatch"):
        validation.validate_gaia_response(gaia, requested_rows=1)


@pytest.mark.parametrize("bad_ra", [float("nan"), -0.1, 360.0, float("inf")])
def test_remote_schema_rejects_invalid_coordinates(bad_ra: float) -> None:
    gaia = _joined_sources(1).loc[:, validation.GAIA_RESPONSE_COLUMNS].copy()
    gaia.loc[0, "ra"] = bad_ra
    with pytest.raises(ValueError):
        validation.validate_gaia_response(gaia, requested_rows=1)


def test_remote_schema_rejects_duplicate_source_ids() -> None:
    gaia = _joined_sources(2).loc[:, validation.GAIA_RESPONSE_COLUMNS].copy()
    gaia.loc[1, "gaia_dr3_source_id"] = gaia.loc[0, "gaia_dr3_source_id"]
    with pytest.raises(ValueError, match="duplicate"):
        validation.validate_gaia_response(gaia, requested_rows=2)


def test_allwise_and_tmass_live_shapes_validate_with_optional_values() -> None:
    joined = _joined_sources(2)
    ids = {1, 2}
    allwise = joined.loc[:, validation.ALLWISE_RESPONSE_COLUMNS].copy()
    allwise.loc[0, ["w4mpro", "w4mpro_error", "w4snr"]] = np.nan
    validation.validate_allwise_response(allwise, requested_ids=ids)
    tmass = joined.loc[:, validation.TMASS_RESPONSE_COLUMNS].copy()
    tmass.loc[0, ["tmass_j_m", "tmass_j_msigcom", "tmass_h_m", "tmass_h_msigcom"]] = np.nan
    validation.validate_tmass_response(tmass, requested_ids=ids)


def test_source_id_inputs_are_bounded_and_unique() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        sources.build_target_adql([1, 1])
    with pytest.raises(ValueError, match="10000"):
        sources.build_target_adql(range(1, validation.MAX_CLI_SOURCE_IDS + 2))
    with pytest.raises(ValueError, match="500-source"):
        sources.build_allwise_for_ids_adql(range(1, 502))


def test_exclusions_reject_more_than_100_matches_per_source() -> None:
    rows = [
        {
            "gaia_dr3_source_id": 1,
            "exclusion_catalog": "SIMBAD",
            "exclusion_class": "AGN",
            "matched_object_id": f"obj-{index}",
            "matched_otype": "AGN",
            "angular_distance_arcsec": 1.0,
            "catalog_release": "test",
        }
        for index in range(validation.MAX_MATCHES_PER_SOURCE_CATALOG + 1)
    ]
    with pytest.raises(ValueError, match="retained-match"):
        validation.validate_exclusions(pd.DataFrame(rows, columns=validation.EXCLUSION_COLUMNS))


def test_repository_local_credentials_are_rejected_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = Path(__file__).resolve().parents[1] / "do-not-use-secret.txt"
    monkeypatch.setenv("PHAROS_GAIA_CREDENTIALS", str(secret_path))
    with pytest.raises(PermissionError) as raised:
        sources._resolve_credentials_path()  # noqa: SLF001 - security-boundary test
    assert str(secret_path) not in str(raised.value)


@pytest.mark.parametrize("value", ["/tmp/output", "../outside", "controls/../../outside"])
def test_new_builder_rejects_output_paths_outside_repository(value: str) -> None:
    with pytest.raises(ValueError):
        cli._resolve_repository_relative_path(value, label="output")  # noqa: SLF001


def test_credentials_must_be_mode_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = tmp_path / "gaia.txt"
    credential.write_text("user\nsecret\n", encoding="utf-8")
    credential.chmod(0o644)
    monkeypatch.setenv("PHAROS_GAIA_CREDENTIALS", str(credential))
    with pytest.raises(PermissionError, match="0600"):
        sources._resolve_credentials_path()  # noqa: SLF001 - security-boundary test


def test_manifest_rejects_unknown_field_and_wrong_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    import yaml

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    extra = copy.deepcopy(payload)
    extra["surprise"] = True
    with pytest.raises(ValueError, match="unexpected"):
        artifacts.validate_control_manifest(extra)
    payload["status"] = "candidate"
    with pytest.raises(ValueError, match="status"):
        artifacts.validate_control_manifest(payload)


def test_manifest_rejects_absolute_generating_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _valid_manifest(tmp_path, monkeypatch)
    import yaml

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["generating_command"] = "python /Users/example/private/build.py"
    with pytest.raises(ValueError, match="absolute"):
        artifacts.validate_control_manifest(payload)


def test_conformant_artifact_round_trip_and_hash_tamper_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, controls_path = _valid_manifest(tmp_path, monkeypatch)
    loaded = artifacts.load_control_artifact(manifest_path)
    assert loaded["gaia_dr3_source_id"].tolist() == [1, 2]
    with controls_path.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ValueError, match="SHA-256"):
        artifacts.load_control_artifact(manifest_path)


def test_legacy_parquet_without_manifest_is_refused(tmp_path: Path) -> None:
    legacy = tmp_path / "quiet_negative.parquet"
    _joined_sources(1).to_parquet(legacy, index=False)
    with pytest.raises(FileNotFoundError, match="manifest"):
        artifacts.load_control_artifact(tmp_path / "manifest.yaml")


def test_raw_checkpoint_round_trip_and_legacy_refusal(tmp_path: Path) -> None:
    raw = _joined_sources(2)
    raw["galactic_l"] = [1.0, 1.0]
    raw["galactic_b"] = [30.0, -30.0]
    cache = tmp_path / "raw.parquet"
    query_hash = hashlib.sha256(b"joined query").hexdigest()
    strata = [asdict(item) for item in sources.build_sampling_strata(2)]
    cursor = 0
    for item in strata:
        item["collected_rows"] = item["quota"]
        if item["quota"]:
            cursor += item["quota"]
            item["cursor_source_id"] = cursor
    manifest_path = artifacts.write_raw_checkpoint(
        cache_path=cache,
        frame=raw,
        query_traces=[
            {
                "service": "Gaia TAP joined",
                "endpoint": artifacts.GAIA_ENDPOINT,
                "query_sha256": query_hash,
                "input_sha256": query_hash,
                "response_sha256": artifacts.sha256_frame(raw),
                "response_rows": 2,
                "requested_at_utc": "2026-08-05T19:59:00Z",
                "received_at_utc": "2026-08-05T20:00:00Z",
            }
        ],
        gaia_rows=2,
        retrieved_at_utc="2026-08-05T20:00:00Z",
        generating_command="python -m pharos.cli build_quiet_negative_v012",
        selection_target_rows=2,
        selection_strata=strata,
    )
    loaded, manifest = artifacts.load_raw_checkpoint(cache)
    assert loaded["gaia_dr3_source_id"].tolist() == [1, 2]
    assert sum(item["collected_rows"] for item in manifest["selection_strata"]) == 2
    assert manifest_path == artifacts.raw_manifest_path(cache)

    import yaml

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for field, replacement in (
        ("git_commit", "0" * 40),
        ("source_tree_sha256", "0" * 64),
        ("uv_lock_sha256", "0" * 64),
    ):
        substituted = copy.deepcopy(payload)
        substituted["software"][field] = replacement
        artifacts.atomic_write_yaml(substituted, manifest_path)
        with pytest.raises(ValueError, match="software provenance"):
            artifacts.load_raw_checkpoint(cache)

    manifest_path.unlink()
    with pytest.raises(RuntimeError, match="legacy, incomplete, or invalid"):
        sources.fetch_quiet_negative_controls(cache, limit=2, use_cache=True)


def test_simbad_query_is_fixed_and_upload_bound() -> None:
    query = control_population._simbad_query_text()  # noqa: SLF001 - frozen query test
    assert "TAP_UPLOAD.targets" in query
    assert "JOIN otypes" in query
    assert "30" not in query  # radius is converted to fixed degrees, not interpolated input
    assert control_population.SIMBAD_SOURCE_CHUNK <= validation.MAX_NETWORK_SOURCE_CHUNK

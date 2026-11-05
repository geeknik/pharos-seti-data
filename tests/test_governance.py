"""Mechanical checks for Pharos governance and protected scientific state."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_PREREGISTRATION = {
    "pre_registration/FROZEN.md": (
        5466,
        "57d6284668cff07e165d5a74c5f3aa655c850b56aaf322288f3cbc3b8caf5fd5",
    ),
    "pre_registration/failed_attempts/v0.1.1_attempt1_calibrated_betas.yaml": (
        1644,
        "736b6cb0b6599b3086a0230d27b81af0516eb39296181df8fa644ad6bb6dd682",
    ),
    "pre_registration/failed_attempts/v0.1.1_attempt1_failure_record.md": (
        7340,
        "54d873dbb7c52ce3c185a0c400b158f98b5e6ed4d0c478b5edabe76c471f88fb",
    ),
    "pre_registration/failed_attempts/v0.1.2_hardened_control_population.md": (
        15481,
        "a6e32d509e31c3e346e79a81eb70b56d7d5310872624480742081b1387853256",
    ),
    "pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md": (
        10828,
        "d9ad5d0fecbed29a77cbecc78a9bf238ef500dbc40fba342f4b52de5c9e95a89",
    ),
    "pre_registration/v0.1.2_subtype_confounders_and_xray_evidence.md": (
        19123,
        "68e4f2d3359a5c4f208426d80a56f58788bdea6003e07ae0a75dc68cbcc259eb",
    ),
    "pre_registration/v0.1.3_control_population.md": (
        87851,
        "b6ba49cc17743eabe9f32b930f318dfe93d3e6778a4c41f4023a850545bfae43",
    ),
    "pre_registration/v0.1_ir_benchmark.md": (
        10494,
        "ff35549f2ebbb5befd48e07248918fc608992dae54529adc118371249afa0202",
    ),
}

PUBLIC_CLAIM_PATHS = (
    "README.md",
    "manuscript.md",
    "RELEASE_NOTES_v0.1.0.md",
    "docs/model_card.md",
    "docs/release_manifest_v0.1.0.md",
)

FORBIDDEN_PUBLIC_CLAIMS = (
    re.compile(r"\balien signal\b", re.IGNORECASE),
    re.compile(r"\bDyson sphere detection\b", re.IGNORECASE),
    re.compile(r"\blikely technology\b", re.IGNORECASE),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_status_is_strict_and_fail_closed() -> None:
    status = tomllib.loads((ROOT / "status.toml").read_text(encoding="utf-8"))

    assert set(status) == {
        "schema_version",
        "as_of_utc",
        "scientific_state_commit",
        "governance",
        "authorization",
        "release",
        "attempts",
        "dependency_audit",
    }
    assert status["schema_version"] == "pharos.project-status.v1"
    assert status["governance"]["operator_edit_only"] is True
    assert set(status["authorization"]) == {
        "catalog_acquisition",
        "checkpoint_creation",
        "external_exclusion_requests",
        "model_fit",
        "source_scoring",
        "scientific_release",
        "public_candidate_announcement",
        "git_push",
        "website_deploy",
    }
    assert not any(status["authorization"].values())
    assert status["release"]["latest_public_version"] == "v0.1.0"
    assert status["release"]["latest_public_class"] == "pilot_benchmark"
    assert status["release"]["latest_public_fully_conformant"] is False

    v013 = status["attempts"]["v0_1_3"]
    assert v013["preregistration_state"] == "frozen"
    assert v013["implementation_state"] == "blocked"
    assert v013["acquisition_state"] == "prohibited"
    assert v013["authorized_reviewer_signing_key_sha256"] == []
    assert v013["required_supersession"] == "v0.1.4"
    assert len(v013["blockers"]) == 3

    audit = status["dependency_audit"]
    assert audit["passed"] is False
    assert audit["finding_count"] == 17
    assert audit["certifi_identity_frozen_in_v0_1_3"] is True


def test_complete_preregistration_inventory_is_byte_identical() -> None:
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "pre_registration").rglob("*")
        if path.is_file()
    }
    assert actual == set(PROTECTED_PREREGISTRATION)

    for relative, (expected_bytes, expected_sha256) in PROTECTED_PREREGISTRATION.items():
        path = ROOT / relative
        payload = path.read_bytes()
        assert len(payload) == expected_bytes, relative
        assert _sha256(path) == expected_sha256, relative


def test_agent_file_remains_bounded_and_points_to_authorities() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(agents.splitlines()) <= 250
    for required in (
        "status.toml",
        "docs/scientific_standards.md",
        "pre_registration/FROZEN.md",
        "tests/test_governance.py",
        ".github/CODEOWNERS",
    ):
        assert required in agents


def test_principal_public_claim_surfaces_avoid_forbidden_shorthand() -> None:
    for relative in PUBLIC_CLAIM_PATHS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PUBLIC_CLAIMS:
            assert pattern.search(text) is None, f"{relative}: {pattern.pattern}"

"""v0.1 pass-criterion benchmark: Hephaistos candidate demotion.

Operational definition of the v0.1 wedge benchmark from
``pre_registration/v0.1_ir_benchmark.md`` §7.

The pipeline must:
  - Demote candidate G into ``discard_confounded``.
  - Demote candidates A and B into ``discard_confounded`` or
    ``needs_human_review``.
  - Not auto-promote candidates C, D, E, F into top-tier ``ir_followup``
    without independent inspection.

The test requires two cached data fixtures:
  - ``controls/cache/quiet_negative.parquet`` — the pre-registered
    quiet-negative control population (Gaia DR3 + AllWISE + 2MASS join).
  - ``controls/cache/hephaistos_join.parquet`` — the Gaia + AllWISE +
    2MASS join row for each of the seven Suazo et al. (2024) candidates.

If either fixture is missing, the test is skipped with a clear pointer
to the fetch command. To populate:

    python -m pharos.cli fetch_quiet_negative \\
        --output controls/cache/quiet_negative.parquet --limit 100000
    python -m pharos.cli fetch_hephaistos \\
        --registry controls/hephaistos.yaml \\
        --output controls/cache/hephaistos_join.parquet

(The ``pharos.cli`` entry points are deferred to a follow-up commit.)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from pharos import calibrate, confounders, ir_sed

REPO_ROOT = Path(__file__).resolve().parents[1]
HEPHAISTOS_YAML = REPO_ROOT / "controls" / "hephaistos.yaml"
QUIET_NEGATIVE_CACHE = REPO_ROOT / "controls" / "cache" / "quiet_negative.parquet"
HEPHAISTOS_JOIN_CACHE = REPO_ROOT / "controls" / "cache" / "hephaistos_join.parquet"

# Pre-registered class thresholds. Source:
# pre_registration/v0.1_ir_benchmark.md §8.
DISCARD_CONFOUNDED_PENALTY: float = 4.0
NEEDS_HUMAN_REVIEW_PENALTY_MIN: float = 2.0
NEEDS_HUMAN_REVIEW_EVIDENCE_MIN: float = 2.0
IR_FOLLOWUP_LEAD_MIN: float = 3.0
IR_FOLLOWUP_PENALTY_MAX: float = 2.0
IR_FOLLOWUP_FDR_MAX: float = 0.05


def _classify(
    lead_score: float,
    ir_evidence: float,
    penalty: float,
    q_value: float,
) -> str:
    if penalty >= DISCARD_CONFOUNDED_PENALTY:
        return "discard_confounded"
    if (
        penalty >= NEEDS_HUMAN_REVIEW_PENALTY_MIN
        and ir_evidence >= NEEDS_HUMAN_REVIEW_EVIDENCE_MIN
    ):
        return "needs_human_review"
    if (
        lead_score >= IR_FOLLOWUP_LEAD_MIN
        and penalty < IR_FOLLOWUP_PENALTY_MAX
        and q_value <= IR_FOLLOWUP_FDR_MAX
    ):
        return "ir_followup"
    return "no_action"


@pytest.fixture(scope="module")
def hephaistos_registry() -> dict:
    with open(HEPHAISTOS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def quiet_negative_controls() -> pd.DataFrame:
    if not QUIET_NEGATIVE_CACHE.exists():
        pytest.skip(
            f"quiet-negative cache missing: {QUIET_NEGATIVE_CACHE}. "
            "Run `python -m pharos.cli fetch_quiet_negative` to populate."
        )
    return pd.read_parquet(QUIET_NEGATIVE_CACHE)


@pytest.fixture(scope="module")
def hephaistos_join() -> pd.DataFrame:
    if not HEPHAISTOS_JOIN_CACHE.exists():
        pytest.skip(
            f"Hephaistos join cache missing: {HEPHAISTOS_JOIN_CACHE}. "
            "Run `python -m pharos.cli fetch_hephaistos` to populate."
        )
    return pd.read_parquet(HEPHAISTOS_JOIN_CACHE)


@pytest.fixture(scope="module")
def classifications(
    hephaistos_registry: dict,
    quiet_negative_controls: pd.DataFrame,
    hephaistos_join: pd.DataFrame,
) -> dict[str, dict]:
    """Run the v0.1 pipeline end-to-end and classify each candidate."""
    controls = ir_sed.add_stratification_bins(
        ir_sed.add_color_indices(quiet_negative_controls)
    )
    targets = ir_sed.add_stratification_bins(
        ir_sed.add_color_indices(hephaistos_join)
    )

    locus = ir_sed.fit_control_locus(controls)
    ir_scores = ir_sed.score_ir_residuals(targets, locus)
    target_raw = ir_sed.composite_ir_evidence_raw(ir_scores.scores)
    control_raw = ir_sed.composite_ir_evidence_raw(
        ir_sed.score_ir_residuals(controls, locus).scores
    )

    target_raw_indexed = pd.Series(
        target_raw.to_numpy(),
        index=ir_scores.scores["gaia_dr3_source_id"].astype("int64").to_numpy(),
        name="target_ir_raw",
    )
    control_raw_indexed = pd.Series(
        control_raw.to_numpy(),
        index=controls["gaia_dr3_source_id"].astype("int64").to_numpy(),
        name="control_ir_raw",
    )

    ir_cal = calibrate.calibrate_ir_evidence(
        target_raw_indexed, control_raw_indexed
    )
    target_confounders = confounders.compute_confounder_scores(targets)
    control_confounders = confounders.compute_confounder_scores(controls)

    coverage_confidence = pd.Series(1.0, index=ir_cal.table.index)
    target_lead = calibrate.compute_lead_scores(
        ir_cal.table["ir_evidence"],
        coverage_confidence,
        target_confounders.penalty,
    )
    control_ir_cal = calibrate.calibrate_ir_evidence(
        control_raw_indexed, control_raw_indexed
    )
    control_lead = calibrate.compute_lead_scores(
        control_ir_cal.table["ir_evidence"],
        pd.Series(1.0, index=control_ir_cal.table.index),
        control_confounders.penalty,
    )
    lead_cal = calibrate.calibrate_lead_scores(target_lead, control_lead)

    label_by_id = {
        int(c["gaia_dr3_source_id"]): c["label"]
        for c in hephaistos_registry["candidates"]
    }
    out: dict[str, dict] = {}
    for source_id, row in lead_cal.table.iterrows():
        sid = int(source_id)
        if sid not in label_by_id:
            continue
        label = label_by_id[sid]
        ir_evidence = ir_cal.table.loc[sid, "ir_evidence"]
        penalty = target_confounders.penalty.loc[sid]
        out[label] = {
            "gaia_dr3_source_id": sid,
            "ir_evidence": float(ir_evidence),
            "penalty": float(penalty),
            "lead_score": float(row["lead_score"]),
            "fdr_q_value": float(row["fdr_q_value_within_coverage_class"]),
            "class": _classify(
                lead_score=float(row["lead_score"]),
                ir_evidence=float(ir_evidence),
                penalty=float(penalty),
                q_value=float(row["fdr_q_value_within_coverage_class"]),
            ),
        }
    return out


def test_candidate_g_is_discard_confounded(classifications: dict[str, dict]) -> None:
    """Pass: candidate G lands in discard_confounded."""
    g = classifications.get("G")
    assert g is not None, "candidate G missing from pipeline output"
    assert g["class"] == "discard_confounded", (
        f"v0.1 confounder model failed to demote candidate G: {g}"
    )


def test_candidate_b_demoted(classifications: dict[str, dict]) -> None:
    """Pass: candidate B lands in discard_confounded or needs_human_review.

    B is flagged via its W1<->W3 photocentre offset (3.21" RA per Suazo
    et al. 2024 Table 7).
    """
    cand = classifications.get("B")
    assert cand is not None, "candidate B missing from pipeline output"
    assert cand["class"] in {"discard_confounded", "needs_human_review"}, (
        f"v0.1 failed to demote suspected contaminant B: {cand}"
    )


def test_candidate_a_not_promoted(classifications: dict[str, dict]) -> None:
    """Pass: candidate A is not auto-promoted to ir_followup.

    A's contamination evidence is from archival radio cross-match (Ren,
    Garrett & Siemion 2024), not the IR layer. Full demotion of A
    requires the radio modality (v0.3); the v0.1 pass criterion is the
    softer bar that A is not promoted to top-tier IR follow-up. See
    pre_registration/v0.1_ir_benchmark.md §7.
    """
    cand = classifications.get("A")
    assert cand is not None, "candidate A missing from pipeline output"
    assert cand["class"] != "ir_followup", (
        f"v0.1 auto-promoted A despite its non-IR contamination evidence: {cand}"
    )


@pytest.mark.parametrize("label", ["C", "D", "E", "F"])
def test_unresolved_candidates_not_auto_promoted(
    classifications: dict[str, dict], label: str
) -> None:
    """Pass: C, D, E, F are not auto-promoted to ir_followup."""
    cand = classifications.get(label)
    assert cand is not None, f"candidate {label} missing from pipeline output"
    assert cand["class"] != "ir_followup", (
        f"v0.1 auto-promoted unresolved candidate {label} without "
        f"independent inspection: {cand}"
    )

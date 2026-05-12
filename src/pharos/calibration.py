"""β-weight calibration for Pharos v0.1.1.

Pre-registration v0.1.1 §3 fixes the procedure: a non-negative L2
logistic regression over the eight P_IR components, fit on a binary
label (`1 = contaminant_positive`, `0 = quiet_negative`) with
`class_weight='balanced'` and `C=1.0`. Bias term is dropped.
Non-negativity is enforced via post-clip — coefficients that come back
negative after the L2 fit are clipped to zero and the final β is the
clipped vector.

Output: a `calibrated_betas_v0.1.1.yaml` artifact recording the
calibrated weights, the input-fixture SHA-256s, the sklearn version,
and the random seed. Confounders module loads this YAML at runtime if
present and falls back to the pre-registered v0.1 β otherwise.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pharos import confounders, ir_sed

logger = logging.getLogger(__name__)

# Pre-registered fit parameters. Pre-reg v0.1.1 §3.1.
LOGREG_C: float = 1.0
LOGREG_MAX_ITER: int = 1000
LOGREG_CLASS_WEIGHT: str = "balanced"
RANDOM_STATE: int = 0


@dataclass(frozen=True)
class CalibrationResult:
    """Fit result with diagnostics.

    With ``fit_intercept=False`` (pre-reg §3.1), the decision boundary
    at proba=0.5 is not meaningful — without a bias the model can only
    *rank* sources by β·P, not assign absolute probabilities. The right
    quality metric is therefore ROC AUC. ``train_accuracy`` is reported
    for transparency but should not be the primary check.
    """

    betas: dict[str, float]  # calibrated, non-negative-clipped β per component
    raw_betas: dict[str, float]  # pre-clip coefficients (for transparency)
    train_loss: float  # cross-entropy with calibrated (post-clip) β
    train_accuracy: float  # fraction correct at threshold 0.5 (biased without intercept)
    train_auc: float  # ROC AUC — the meaningful ranking metric
    score_separation: float  # mean(β·P | contaminant) - mean(β·P | control)
    n_contaminants: int
    n_controls: int
    fit_metadata: dict


def _confounder_feature_matrix(
    df: pd.DataFrame, component_order: list[str]
) -> np.ndarray:
    """Compute the P_IR component vector for each row of df.

    Returns an array of shape (n_rows, n_components) where columns are
    in ``component_order``.
    """
    scores = confounders.compute_confounder_scores(df)
    cols = [f"p_{name}" for name in component_order]
    return scores.vector[cols].to_numpy(dtype=float)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def calibrate_betas(
    contaminants: pd.DataFrame,
    controls: pd.DataFrame,
    *,
    component_order: list[str] | None = None,
    random_state: int = RANDOM_STATE,
) -> CalibrationResult:
    """Fit non-negative L2 logistic regression on the P_IR component vector.

    The label is binary: 1 for contaminants, 0 for controls. Class
    balance is handled via ``class_weight='balanced'`` in sklearn.
    Non-negativity is enforced by post-clipping coefficients ≤ 0 to 0
    and re-evaluating the cross-entropy with the clipped weights.

    Args:
      contaminants: dataframe with the columns confounders.compute_confounder_scores
                    expects; one row per labeled contaminant_positive source.
      controls: same schema, one row per labeled quiet_negative source.
      component_order: optional list of component names; defaults to the
                       sorted keys of confounders.BETA_WEIGHTS.
    """
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
    from sklearn.metrics import log_loss, roc_auc_score  # type: ignore[import-untyped]

    if component_order is None:
        component_order = list(confounders.BETA_WEIGHTS.keys())

    X_pos = _confounder_feature_matrix(contaminants, component_order)
    X_neg = _confounder_feature_matrix(controls, component_order)
    X = np.vstack([X_pos, X_neg])
    y = np.concatenate([np.ones(len(X_pos)), np.zeros(len(X_neg))])

    n_pos = len(X_pos)
    n_neg = len(X_neg)
    if n_pos < 3 or n_neg < 30:
        raise ValueError(
            f"calibration needs at least 3 contaminants and 30 controls; "
            f"got {n_pos} and {n_neg}"
        )
    logger.info(
        "fitting non-negative L2 logistic regression: %d contaminants, %d controls, %d features",
        n_pos, n_neg, X.shape[1],
    )

    model = LogisticRegression(
        C=LOGREG_C,
        solver="lbfgs",
        max_iter=LOGREG_MAX_ITER,
        class_weight=LOGREG_CLASS_WEIGHT,
        fit_intercept=False,  # pre-reg §3.1: drop bias term
        random_state=random_state,
    )
    model.fit(X, y)
    raw_coef = model.coef_[0]
    # Non-negativity clip.
    clipped_coef = np.clip(raw_coef, a_min=0.0, a_max=None)

    # Re-evaluate metrics with the clipped weights. Without an intercept
    # the threshold-at-0.5 accuracy is biased; ROC AUC measures ranking
    # quality, which is what β·P is meant to provide.
    z = X @ clipped_coef
    proba = 1.0 / (1.0 + np.exp(-z))
    eps = 1e-12
    proba = np.clip(proba, eps, 1.0 - eps)
    train_loss = float(log_loss(y, proba))
    train_accuracy = float(((proba >= 0.5).astype(int) == y).mean())
    # AUC is undefined when one class is missing; guard.
    try:
        train_auc = float(roc_auc_score(y, z))
    except ValueError:
        train_auc = float("nan")
    contam_mean = float(z[y == 1].mean()) if (y == 1).any() else float("nan")
    control_mean = float(z[y == 0].mean()) if (y == 0).any() else float("nan")
    score_separation = contam_mean - control_mean

    raw_betas = {name: float(raw_coef[i]) for i, name in enumerate(component_order)}
    betas = {name: float(clipped_coef[i]) for i, name in enumerate(component_order)}

    fit_metadata = {
        "python_version": sys.version.split()[0],
        "sklearn_version": _sklearn_version(),
        "fit_params": {
            "penalty": "l2",
            "C": LOGREG_C,
            "solver": "lbfgs",
            "max_iter": LOGREG_MAX_ITER,
            "class_weight": LOGREG_CLASS_WEIGHT,
            "fit_intercept": False,
            "random_state": int(random_state),
        },
        "n_components": int(X.shape[1]),
        "non_negative_clipping_changed_components": int(
            sum(1 for r, c in zip(raw_coef, clipped_coef) if not np.isclose(r, c))
        ),
    }

    logger.info(
        "calibration: AUC=%.3f, loss=%.4f, score_sep=%.3f, %d/%d non-zero β",
        train_auc, train_loss, score_separation,
        int((np.array(list(betas.values())) > 0).sum()),
        len(betas),
    )
    return CalibrationResult(
        betas=betas,
        raw_betas=raw_betas,
        train_loss=train_loss,
        train_accuracy=train_accuracy,
        train_auc=train_auc,
        score_separation=score_separation,
        n_contaminants=n_pos,
        n_controls=n_neg,
        fit_metadata=fit_metadata,
    )


def _sklearn_version() -> str:
    import sklearn  # type: ignore[import-untyped]

    return sklearn.__version__


def write_calibration_yaml(
    result: CalibrationResult,
    output_path: Path,
    *,
    contaminants_path: Path,
    controls_path: Path,
    pre_reg_path: Path,
) -> None:
    """Persist the calibration to a YAML artifact with full provenance."""
    import yaml

    payload = {
        "schema_version": 1,
        "spec": "pre_registration/v0.1.1_calibrated_betas_and_xray_hot_dog.md §3",
        "calibrated_betas": result.betas,
        "raw_pre_clip_betas": result.raw_betas,
        "train_loss": result.train_loss,
        "train_accuracy": result.train_accuracy,
        "train_auc": result.train_auc,
        "score_separation": result.score_separation,
        "n_contaminants": result.n_contaminants,
        "n_controls": result.n_controls,
        "fit_metadata": result.fit_metadata,
        "input_fixtures": {
            "contaminants": {"path": str(contaminants_path), "sha256": _sha256(contaminants_path)},
            "controls": {"path": str(controls_path), "sha256": _sha256(controls_path)},
            "pre_registration": {"path": str(pre_reg_path), "sha256": _sha256(pre_reg_path)},
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    logger.info("calibrated β written to %s", output_path)


def load_calibration_yaml(path: Path) -> dict[str, float] | None:
    """Load the calibrated β weights from a YAML artifact, or return None.

    Returns None if the file doesn't exist. The confounders module
    calls this at import time; a missing file means "use the
    pre-registered v0.1 initialization weights."
    """
    import yaml

    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    return payload.get("calibrated_betas")

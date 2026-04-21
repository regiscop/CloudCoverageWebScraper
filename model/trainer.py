"""
Module 5 — Forecasting model trainer.

Implements Levels 1 and 2 from §7.1:
  - Level 1 : optical-flow cloud-motion extrapolation (baseline, no training)
  - Level 2 : XGBoost multi-output regressor for H+1 … H+48

Temporal split (§7.2): train / val / test — NEVER random shuffle on time series.
Evaluation: MAE, RMSE, skill score vs NWP baseline.
Improvement C: Optuna walk-forward hyperparameter tuning (run_optuna_tuning).
"""

import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

from config import FORECAST_HORIZONS_H

optuna.logging.set_verbosity(optuna.logging.WARNING)

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "cloud_index_vis",
    "cloud_std_vis",
    "cloud_index_ir",
    "motion_u",
    "motion_v",
    "cloud_cover_nwp",
    "ghi_clearsky",
    "solar_elevation",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
]

TARGET_COL = "cloud_index_vis"  # predict future cloud index
MODEL_DIR  = Path("models")


# ---------------------------------------------------------------------------
# Level 1 — optical flow extrapolation (no-training baseline)
# ---------------------------------------------------------------------------

def extrapolate_cloud_motion(
    cloud_index: float,
    motion_u: float,
    motion_v: float,
    horizon_h: int,
    pixel_to_fraction: float = 0.001,
) -> float:
    """
    Naïve linear extrapolation of cloud coverage using motion vector.
    Returns predicted cloud_index at T+horizon_h.
    pixel_to_fraction converts pixel displacement to a cloud index delta.
    """
    displacement = np.sqrt(motion_u**2 + motion_v**2) * horizon_h
    delta = displacement * pixel_to_fraction
    # Motion disperses clouds over longer horizons — dampen linearly
    dampening = max(0.0, 1.0 - horizon_h / 6.0)
    predicted = cloud_index + delta * dampening
    return float(np.clip(predicted, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Level 2 — XGBoost multi-horizon model
# ---------------------------------------------------------------------------

def make_targets(df: pd.DataFrame, horizons: list[int] = FORECAST_HORIZONS_H) -> pd.DataFrame:
    """
    Create lead targets for each forecast horizon.
    Input df must be sorted by time and have a 1-h frequency per zone.
    """
    df = df.sort_values("captured_at").copy()
    for h in horizons:
        df[f"target_h{h:02d}"] = df[TARGET_COL].shift(-h)
    return df.dropna()


def temporal_split(
    df: pd.DataFrame,
    val_days: int = 8,
    test_days: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Chronological train/val/test split.
    test  : last test_days days
    val   : preceding val_days days
    train : everything before that
    """
    df = df.sort_values("captured_at")
    cutoff_test = df["captured_at"].max() - timedelta(days=test_days)
    cutoff_val  = cutoff_test - timedelta(days=val_days)

    train = df[df["captured_at"] <  cutoff_val]
    val   = df[(df["captured_at"] >= cutoff_val) & (df["captured_at"] < cutoff_test)]
    test  = df[df["captured_at"] >= cutoff_test]

    logger.info(
        "Split — train: %d, val: %d, test: %d", len(train), len(val), len(test)
    )
    return train, val, test


def train_xgboost(
    train: pd.DataFrame,
    val: pd.DataFrame,
    horizons: list[int] = FORECAST_HORIZONS_H,
    n_estimators: int = 400,
    max_depth: int = 6,
    learning_rate: float = 0.05,
) -> dict[int, XGBRegressor]:
    """Train one XGBRegressor per forecast horizon; returns {horizon: model}."""
    models: dict[int, XGBRegressor] = {}

    X_train = train[FEATURE_COLS].fillna(0)
    X_val   = val[FEATURE_COLS].fillna(0)

    for h in horizons:
        target_col = f"target_h{h:02d}"
        if target_col not in train.columns:
            logger.warning("Target %s missing — skipping horizon H+%d", target_col, h)
            continue

        y_train = train[target_col]
        y_val   = val[target_col]

        model = XGBRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            eval_metric="mae",
            early_stopping_rounds=30,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        models[h] = model
        logger.info("Trained XGBoost H+%02d — best iter: %d", h, model.best_iteration)

    return models


def evaluate(
    models: dict[int, XGBRegressor],
    test: pd.DataFrame,
    nwp_col: str = "cloud_cover_nwp",
) -> pd.DataFrame:
    """
    Evaluate models on the test set.
    Returns a DataFrame with MAE, RMSE, and skill score vs NWP for each horizon.
    """
    X_test = test[FEATURE_COLS].fillna(0)
    results = []

    for h, model in models.items():
        target_col = f"target_h{h:02d}"
        if target_col not in test.columns:
            continue

        y_true = test[target_col].values
        y_pred = model.predict(X_test)

        mae  = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))

        # Skill score: improvement over NWP persistence baseline
        if nwp_col in test.columns:
            nwp_norm = test[nwp_col].fillna(0).values / 100.0  # % → fraction
            nwp_mae  = mean_absolute_error(y_true, nwp_norm)
            skill    = 1.0 - mae / nwp_mae if nwp_mae > 0 else float("nan")
        else:
            skill = float("nan")

        results.append({"horizon_h": h, "MAE": mae, "RMSE": rmse, "skill_score": skill})
        logger.info("H+%02d  MAE=%.4f  RMSE=%.4f  Skill=%.3f", h, mae, rmse, skill)

    return pd.DataFrame(results)


def save_models(models: dict[int, XGBRegressor], version: str = "v1") -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = MODEL_DIR / f"xgboost_{version}.pkl"
    with open(out, "wb") as f:
        pickle.dump(models, f)
    logger.info("Models saved to %s", out)
    return out


def load_models(version: str = "v1") -> dict[int, XGBRegressor]:
    path = MODEL_DIR / f"xgboost_{version}.pkl"
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------------------
# Full training pipeline
# ---------------------------------------------------------------------------

def run_training_pipeline(df: pd.DataFrame, model_version: str = "v1") -> pd.DataFrame:
    """
    End-to-end pipeline:
      1. Add lead targets
      2. Temporal split
      3. Train XGBoost
      4. Evaluate on test set
      5. Save models
    Returns evaluation metrics DataFrame.
    """
    df_with_targets = make_targets(df)
    train, val, test = temporal_split(df_with_targets)
    models = train_xgboost(train, val)
    metrics = evaluate(models, test)
    save_models(models, version=model_version)
    return metrics


# ---------------------------------------------------------------------------
# Improvement C — Optuna walk-forward hyperparameter tuning
# ---------------------------------------------------------------------------

def _walk_forward_mae(
    df: pd.DataFrame,
    horizon: int,
    params: dict,
    n_folds: int = 3,
    fold_days: int = 7,
) -> float:
    """
    Walk-forward cross-validation over `n_folds` consecutive test windows.
    Returns mean MAE across folds for a single horizon.
    """
    target_col = f"target_h{horizon:02d}"
    if target_col not in df.columns:
        return float("inf")

    df = df.sort_values("captured_at").dropna(subset=[target_col])
    total_days = (df["captured_at"].max() - df["captured_at"].min()).days
    # Reserve enough history for at least one training fold
    if total_days < fold_days * (n_folds + 1):
        return float("inf")

    maes = []
    for fold in range(n_folds):
        test_end   = df["captured_at"].max() - timedelta(days=fold * fold_days)
        test_start = test_end - timedelta(days=fold_days)
        val_start  = test_start - timedelta(days=fold_days)

        train = df[df["captured_at"] <  val_start]
        val   = df[(df["captured_at"] >= val_start) & (df["captured_at"] < test_start)]
        test  = df[(df["captured_at"] >= test_start) & (df["captured_at"] < test_end)]

        if train.empty or val.empty or test.empty:
            continue

        model = XGBRegressor(
            **params,
            random_state=42,
            n_jobs=-1,
            eval_metric="mae",
            early_stopping_rounds=20,
        )
        model.fit(
            train[FEATURE_COLS].fillna(0), train[target_col],
            eval_set=[(val[FEATURE_COLS].fillna(0), val[target_col])],
            verbose=False,
        )
        y_pred = model.predict(test[FEATURE_COLS].fillna(0))
        maes.append(mean_absolute_error(test[target_col].values, y_pred))

    return float(np.mean(maes)) if maes else float("inf")


def run_optuna_tuning(
    df: pd.DataFrame,
    horizon: int = 1,
    n_trials: int = 50,
    model_version: str = "v1_tuned",
) -> dict:
    """
    Run Optuna hyperparameter search for a given horizon using walk-forward CV.
    Trains and saves the best model for all horizons using the best params found.
    Returns the best params dict.
    """
    df_targets = make_targets(df)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators":     trial.suggest_int("n_estimators", 100, 800),
            "max_depth":        trial.suggest_int("max_depth", 3, 9),
            "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample":        trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "gamma":            trial.suggest_float("gamma", 0.0, 5.0),
            "reg_alpha":        trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
            "reg_lambda":       trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        }
        return _walk_forward_mae(df_targets, horizon, params)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    logger.info("Optuna H+%02d best MAE=%.4f  params=%s", horizon, study.best_value, best_params)

    # Retrain all horizons with the best params found
    train, val, test = temporal_split(df_targets)
    models = train_xgboost(
        train, val,
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        learning_rate=best_params["learning_rate"],
    )
    metrics = evaluate(models, test)
    save_models(models, version=model_version)

    return best_params

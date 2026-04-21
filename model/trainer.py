"""
Module 5 — Forecasting model trainer.

Implements Levels 1 and 2 from §7.1:
  - Level 1 : optical-flow cloud-motion extrapolation (baseline, no training)
  - Level 2 : XGBoost multi-output regressor for H+1 … H+48

Temporal split (§7.2): train / val / test — NEVER random shuffle on time series.
Evaluation: MAE, RMSE, skill score vs NWP baseline.
"""

import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

from config import FORECAST_HORIZONS_H

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

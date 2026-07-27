from __future__ import annotations
from dataclasses import dataclass
import math
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from .features import FeatureSnapshot

FEATURE_COLUMNS = [
    "distance_bps", "log_seconds_remaining", "ret_5s", "ret_15s", "ret_60s",
    "rv_60s", "rv_300s", "trend_ema", "momentum", "orderbook_imbalance"
]

def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

@dataclass
class ProbabilityModel:
    pipeline: object | None = None

    def predict_up(self, f: FeatureSnapshot) -> float:
        if self.pipeline is not None:
            return float(self.pipeline.predict_proba([f.vector()])[0, 1])
        # Transparent fallback: drift-adjusted lognormal approximation.
        t = max(f.seconds_remaining, 1.0)
        sigma_per_sqrt_sec = max(f.rv_60s / math.sqrt(60), 1e-7)
        sigma_horizon = sigma_per_sqrt_sec * math.sqrt(t)
        drift = 0.35*f.momentum + 0.15*f.trend_ema + 0.0002*f.orderbook_imbalance
        z = (math.log(f.btc_price / f.target_price) + drift) / sigma_horizon
        return min(max(normal_cdf(z), 0.001), 0.999)

    @classmethod
    def load(cls, path: str | Path) -> "ProbabilityModel":
        return cls(joblib.load(path))

    def save(self, path: str | Path) -> None:
        if self.pipeline is None:
            raise ValueError("No trained pipeline to save.")
        joblib.dump(self.pipeline, path)

def train_model(df: pd.DataFrame) -> ProbabilityModel:
    x = df.copy()
    x["log_seconds_remaining"] = np.log1p(x["seconds_remaining"].clip(lower=0))
    base = Pipeline([
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    # Calibration improves probability quality; CV must preserve chronology in real research.
    calibrated = CalibratedClassifierCV(base, method="sigmoid", cv=5)
    calibrated.fit(x[FEATURE_COLUMNS], x["settled_up"].astype(int))
    return ProbabilityModel(calibrated)

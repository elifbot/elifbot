"""Walk-Forward Gradient Boosting Sinyal Tahmincisi (LightGBM / XGBoost / Sklearn / NumPy GBDT).

Yalnızca geçmişte kapanmış mumlardan öznitelik çıkarır (sıfır gelecek sızıntısı / no look-ahead):
- Son `horizon` mum etiketlenemediği için eğitim kümesi `X[:-horizon], y[:-horizon]` ile sınırlandırılır.
- Tahmin ise güncel kapanmış son mumun (`X[-1:]`) öznitelikleri üzerinde yapılır.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class _Stump:
    feature_idx: int
    threshold: float
    left_val: float
    right_val: float


class _NumpyGBDTClassifier:
    """Harici C++ bağımlılığı olmadan hızlı çalışan hafif Gradient Boosted Decision Stumps."""

    def __init__(self, n_estimators: int = 25, learning_rate: float = 0.18):
        self.n_estimators = int(n_estimators)
        self.learning_rate = float(learning_rate)
        self.base_log_odds: float = 0.0
        self.stumps: list[_Stump] = []

    @staticmethod
    def _sigmoid(z: np.ndarray | float) -> np.ndarray | float:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_NumpyGBDTClassifier":
        pos_rate = float(np.clip(np.mean(y), 0.05, 0.95))
        self.base_log_odds = float(np.log(pos_rate / (1.0 - pos_rate)))
        f = np.full(len(y), self.base_log_odds, dtype=float)
        self.stumps = []
        quantiles = (0.2, 0.35, 0.5, 0.65, 0.8)

        for _ in range(self.n_estimators):
            p = self._sigmoid(f)
            residual = y - p
            best_loss = float("inf")
            best_stump: _Stump | None = None

            for j in range(X.shape[1]):
                col = X[:, j]
                thresholds = np.unique(np.quantile(col, quantiles))
                for th in thresholds:
                    left = col <= th
                    right = ~left
                    if left.sum() < 4 or right.sum() < 4:
                        continue
                    l_val = float(residual[left].mean())
                    r_val = float(residual[right].mean())
                    pred = np.where(left, l_val, r_val)
                    loss = float(np.mean((residual - pred) ** 2))
                    if loss < best_loss:
                        best_loss = loss
                        best_stump = _Stump(j, float(th), l_val, r_val)

            if best_stump is None:
                break
            col = X[:, best_stump.feature_idx]
            step = np.where(
                col <= best_stump.threshold, best_stump.left_val, best_stump.right_val
            )
            f = f + self.learning_rate * step * 2.0
            self.stumps.append(best_stump)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        f = np.full(X.shape[0], self.base_log_odds, dtype=float)
        for st in self.stumps:
            col = X[:, st.feature_idx]
            step = np.where(col <= st.threshold, st.left_val, st.right_val)
            f = f + self.learning_rate * step * 2.0
        p1 = np.asarray(self._sigmoid(f), dtype=float)
        return np.column_stack([1.0 - p1, p1])


def _select_backend(preferred: str = "auto"):
    if preferred in ("auto", "lightgbm"):
        try:
            import lightgbm as lgb  # type: ignore

            return "lightgbm", lambda: lgb.LGBMClassifier(
                n_estimators=40,
                max_depth=3,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                random_state=42,
                verbose=-1,
            )
        except Exception:
            if preferred == "lightgbm":
                pass
    if preferred in ("auto", "xgboost"):
        try:
            import xgboost as xgb  # type: ignore

            return "xgboost", lambda: xgb.XGBClassifier(
                n_estimators=40,
                max_depth=3,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                eval_metric="logloss",
                random_state=42,
                verbosity=0,
            )
        except Exception:
            pass
    if preferred in ("auto", "sklearn"):
        try:
            from sklearn.ensemble import GradientBoostingClassifier  # type: ignore

            return "sklearn_gbdt", lambda: GradientBoostingClassifier(
                n_estimators=35, max_depth=2, learning_rate=0.08, random_state=42
            )
        except Exception:
            pass
    return "numpy_gbdt", lambda: _NumpyGBDTClassifier(n_estimators=25, learning_rate=0.18)


class MLPredictor:
    """Kapanmış OHLCV mumlarından walk-forward yön olasılığı (`prob_up`) ve `-100..+100` skor üretir."""

    def __init__(
        self,
        horizon: int = 3,
        min_train_bars: int = 80,
        retrain_every: int = 15,
        backend: str = "auto",
    ):
        self.horizon = max(1, int(horizon))
        self.min_train_bars = max(30, int(min_train_bars))
        self.retrain_every = max(1, int(retrain_every))
        self.backend_name, self._factory = _select_backend(backend)
        self._model = None
        self._bars_since_train = 0
        self._last_trained_len = 0

    @staticmethod
    def build_features(df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        lo = df["low"].astype(float)
        v = df["volume"].astype(float)

        ret_1 = c.pct_change(1)
        ret_3 = c.pct_change(3)
        ret_6 = c.pct_change(6)
        ret_12 = c.pct_change(12)

        ema_fast = c.ewm(span=9, adjust=False).mean()
        ema_slow = c.ewm(span=21, adjust=False).mean()
        ema_gap = (ema_fast - ema_slow) / c.replace(0, np.nan)

        delta = c.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        down = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        rsi = (100 - (100 / (1 + rs))) / 100.0 - 0.5

        bb_mid = c.rolling(20).mean()
        bb_std = c.rolling(20).std(ddof=0).replace(0, np.nan)
        bb_z = (c - bb_mid) / bb_std

        tr = pd.concat(
            [(h - lo), (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1
        ).max(axis=1)
        atr_pct = tr.rolling(14).mean() / c.replace(0, np.nan)

        vol_ma = v.rolling(20).mean().replace(0, np.nan)
        vol_ratio = (v / vol_ma) - 1.0

        feats = pd.DataFrame(
            {
                "ret_1": ret_1,
                "ret_3": ret_3,
                "ret_6": ret_6,
                "ret_12": ret_12,
                "ema_gap": ema_gap,
                "rsi_centered": rsi,
                "bb_z": bb_z,
                "atr_pct": atr_pct,
                "vol_ratio": vol_ratio,
            },
            index=df.index,
        )
        return feats.replace([np.inf, -np.inf], np.nan)

    def predict(self, df: pd.DataFrame) -> dict:
        if df is None or len(df) < self.min_train_bars:
            return {
                "score": 0.0,
                "prob_up": 0.5,
                "backend": self.backend_name,
                "trained": False,
                "samples": 0 if df is None else len(df),
            }

        feats = self.build_features(df)
        close = df["close"].astype(float)
        future_ret = close.shift(-self.horizon) / close - 1.0

        valid_train = feats.iloc[: -self.horizon].dropna()
        if len(valid_train) < max(25, self.min_train_bars - 25):
            return {
                "score": 0.0,
                "prob_up": 0.5,
                "backend": self.backend_name,
                "trained": False,
                "samples": len(valid_train),
            }

        y_train = (future_ret.loc[valid_train.index] > 0.0).astype(int).to_numpy()
        X_train = valid_train.to_numpy(dtype=float)

        need_retrain = (
            self._model is None
            or self._bars_since_train >= self.retrain_every
            or abs(len(df) - self._last_trained_len) >= self.retrain_every
        )
        if need_retrain and len(np.unique(y_train)) >= 2:
            model = self._factory()
            model.fit(X_train, y_train)
            self._model = model
            self._bars_since_train = 0
            self._last_trained_len = len(df)
        else:
            self._bars_since_train += 1

        if self._model is None:
            return {
                "score": 0.0,
                "prob_up": 0.5,
                "backend": self.backend_name,
                "trained": False,
                "samples": len(valid_train),
            }

        last_row = feats.iloc[[-1]].ffill().fillna(0.0).to_numpy(dtype=float)
        proba = self._model.predict_proba(last_row)
        prob_up = float(np.clip(proba[0, 1], 0.0, 1.0))
        score = round(float(np.clip((prob_up - 0.5) * 200.0, -100.0, 100.0)), 1)
        return {
            "score": score,
            "prob_up": round(prob_up, 4),
            "backend": self.backend_name,
            "trained": True,
            "samples": len(valid_train),
        }


MLSignalPredictor = MLPredictor

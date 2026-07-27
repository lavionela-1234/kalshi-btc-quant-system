from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import numpy as np

@dataclass
class FeatureSnapshot:
    btc_price: float
    target_price: float
    distance_usd: float
    distance_bps: float
    seconds_remaining: float
    ret_5s: float
    ret_15s: float
    ret_60s: float
    rv_60s: float
    rv_300s: float
    trend_ema: float
    momentum: float
    orderbook_imbalance: float

    def vector(self) -> list[float]:
        return [
            self.distance_bps,
            math.log1p(max(self.seconds_remaining, 0)),
            self.ret_5s,
            self.ret_15s,
            self.ret_60s,
            self.rv_60s,
            self.rv_300s,
            self.trend_ema,
            self.momentum,
            self.orderbook_imbalance,
        ]

class RollingBTCFeatures:
    def __init__(self, max_seconds: int = 900):
        self.points = deque()
        self.max_seconds = max_seconds

    def add(self, timestamp: datetime, price: float) -> None:
        self.points.append((timestamp, price))
        cutoff = timestamp.timestamp() - self.max_seconds
        while self.points and self.points[0][0].timestamp() < cutoff:
            self.points.popleft()

    def _price_ago(self, now: datetime, seconds: int) -> float | None:
        target = now.timestamp() - seconds
        candidate = None
        for t, p in self.points:
            if t.timestamp() <= target:
                candidate = p
            else:
                break
        return candidate

    def _ret(self, now: datetime, current: float, seconds: int) -> float:
        old = self._price_ago(now, seconds)
        return math.log(current / old) if old and old > 0 else 0.0

    def _rv(self, now: datetime, seconds: int) -> float:
        cutoff = now.timestamp() - seconds
        prices = [p for t, p in self.points if t.timestamp() >= cutoff]
        if len(prices) < 3:
            return 0.0
        rets = np.diff(np.log(np.asarray(prices)))
        return float(np.std(rets, ddof=1) * math.sqrt(max(len(rets), 1)))

    def snapshot(
        self,
        now: datetime,
        current_price: float,
        target_price: float,
        close_time: datetime,
        orderbook_imbalance: float,
    ) -> FeatureSnapshot:
        prices = np.asarray([p for _, p in self.points], dtype=float)
        if len(prices) >= 2:
            alpha_fast, alpha_slow = 2/13, 2/49
            fast = slow = prices[0]
            for p in prices[1:]:
                fast = alpha_fast*p + (1-alpha_fast)*fast
                slow = alpha_slow*p + (1-alpha_slow)*slow
            trend = (fast - slow) / current_price
        else:
            trend = 0.0
        ret5 = self._ret(now, current_price, 5)
        ret15 = self._ret(now, current_price, 15)
        ret60 = self._ret(now, current_price, 60)
        return FeatureSnapshot(
            btc_price=current_price,
            target_price=target_price,
            distance_usd=current_price-target_price,
            distance_bps=(current_price-target_price)/target_price*10000,
            seconds_remaining=max((close_time-now).total_seconds(), 0),
            ret_5s=ret5,
            ret_15s=ret15,
            ret_60s=ret60,
            rv_60s=self._rv(now, 60),
            rv_300s=self._rv(now, 300),
            trend_ema=trend,
            momentum=0.5*ret5 + 0.3*ret15 + 0.2*ret60,
            orderbook_imbalance=orderbook_imbalance,
        )

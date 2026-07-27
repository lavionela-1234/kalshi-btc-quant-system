from __future__ import annotations
from dataclasses import dataclass
from .features import FeatureSnapshot

@dataclass
class Signal:
    action: str
    side: str | None
    model_probability: float
    market_probability: float | None
    edge: float
    reason: str

def evaluate_signal(
    f: FeatureSnapshot,
    p_up: float,
    yes_ask: float | None,
    no_ask: float | None,
    min_edge: float,
    cost_buffer: float,
    max_spread: float = 0.08,
    min_seconds: float = 10,
    max_seconds: float = 300,
) -> Signal:
    if yes_ask is None or no_ask is None:
        return Signal("SKIP", None, p_up, None, 0, "Incomplete order book")
    spread = yes_ask - (1-no_ask)
    if spread > max_spread:
        return Signal("SKIP", None, p_up, yes_ask, 0, "Spread too wide")
    if not min_seconds <= f.seconds_remaining <= max_seconds:
        return Signal("SKIP", None, p_up, yes_ask, 0, "Outside time window")

    yes_edge = p_up - yes_ask - cost_buffer
    p_down = 1-p_up
    no_edge = p_down - no_ask - cost_buffer

    if yes_edge >= min_edge and yes_edge >= no_edge:
        return Signal("FLAG", "YES", p_up, yes_ask, yes_edge, "Positive YES expected edge")
    if no_edge >= min_edge:
        return Signal("FLAG", "NO", p_down, no_ask, no_edge, "Positive NO expected edge")
    return Signal("SKIP", None, p_up, yes_ask, max(yes_edge, no_edge), "Insufficient edge")

from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RiskDecision:
    stake_dollars: float
    contracts: int
    method: str
    blocked: bool
    reason: str

def fractional_kelly(
    bankroll: float,
    probability: float,
    contract_price: float,
    kelly_fraction: float = 0.25,
    max_position_fraction: float = 0.02,
) -> RiskDecision:
    if not 0 < contract_price < 1:
        return RiskDecision(0, 0, "kelly", True, "Invalid contract price")
    net_odds = (1-contract_price)/contract_price
    full_kelly = (net_odds*probability - (1-probability))/net_odds
    fraction = max(0.0, full_kelly) * kelly_fraction
    fraction = min(fraction, max_position_fraction)
    stake = bankroll * fraction
    contracts = int(stake / contract_price)
    return RiskDecision(contracts*contract_price, contracts, "fractional_kelly",
                        contracts < 1, "No positive Kelly stake" if contracts < 1 else "OK")

def fixed_risk(
    bankroll: float,
    contract_price: float,
    risk_fraction: float = 0.01,
    max_position_fraction: float = 0.02,
) -> RiskDecision:
    fraction = min(risk_fraction, max_position_fraction)
    stake = bankroll*fraction
    contracts = int(stake/contract_price) if contract_price > 0 else 0
    return RiskDecision(contracts*contract_price, contracts, "fixed_risk",
                        contracts < 1, "Stake below one contract" if contracts < 1 else "OK")

"""Kelly fractionné et mise recommandée."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings


def kelly_fraction(p: float, odds: float, kappa: float = None) -> float:
    """
    f* = Kelly × κ
    Kelly = (p × b - q) / b   où b = cote - 1, q = 1 - p
    """
    kappa = kappa or settings.kelly_kappa
    b = odds - 1
    if b <= 0 or p <= 0:
        return 0.0
    q = 1 - p
    kelly = (p * b - q) / b
    if kelly <= 0:
        return 0.0
    return round(kelly * kappa, 6)


def recommended_stake(
    portfolio: float,
    kelly_f: float,
    rf: float = 1.0,
    max_pct: float = None,
) -> float:
    """
    mise = min(f* × RF × portfolio, max_pct × portfolio)
    RF pondère la mise selon la fiabilité du modèle.
    """
    max_pct = max_pct or settings.max_stake_pct
    raw = kelly_f * rf * portfolio
    capped = max_pct * portfolio
    return round(max(0.0, min(raw, capped)), 2)

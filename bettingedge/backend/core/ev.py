"""Calcul d'espérance de valeur (EV)."""


def ev(p_estimated: float, odds: float) -> float:
    """EV = p × cote - 1. Positif = pari intéressant."""
    return round(p_estimated * odds - 1, 6)


def value(odds_betclic: float, odds_fair: float) -> float:
    """value = cote_betclic / cote_juste - 1. Positif = value bet."""
    if odds_fair <= 0:
        return 0.0
    return round(odds_betclic / odds_fair - 1, 6)


def clv(odds_taken: float, odds_close: float) -> float:
    """CLV = cote_prise / cote_clôture - 1."""
    if odds_close <= 0:
        return 0.0
    return round(odds_taken / odds_close - 1, 6)


def is_positive(ev_value: float, threshold: float = 0.0) -> bool:
    return ev_value > threshold

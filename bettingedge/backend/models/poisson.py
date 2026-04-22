"""
Modèle Poisson générique — aces tennis, corners foot, double fautes.
"""
import math


def pmf(k: int, lam: float) -> float:
    """P(X = k) pour X ~ Poisson(lambda)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def cdf(k: int, lam: float) -> float:
    """P(X ≤ k)."""
    return sum(pmf(i, lam) for i in range(k + 1))


def predict_over(lam: float, threshold: float) -> float:
    """P(X > threshold). threshold peut être non-entier (ex: 8.5)."""
    k = int(math.floor(threshold))
    return 1.0 - cdf(k, lam)


def predict_exact(lam: float, k: int) -> float:
    """P(X = k)."""
    return pmf(k, lam)


def fair_odds(prob: float) -> float:
    """Cote juste = 1 / probabilité."""
    if prob <= 0:
        return 999.0
    return round(1.0 / prob, 4)


def lambda_aces(ace_rate: float, expected_service_games: float) -> float:
    """
    λ_total = ace_rate × E[jeux_de_service]
    ace_rate : % d'aces par jeu de service (ex: 0.06 = 6%)
    expected_service_games : E[jeux de service dans le match]
    """
    return ace_rate * expected_service_games


def lambda_corners(
    avg_corners_home: float,
    avg_corners_away: float,
    xg_diff: float = 0.0,
    alpha: float = 0.15,
) -> float:
    """
    λ_total = (avg_home + avg_away) × (1 + alpha × |xG_diff|)
    """
    base = avg_corners_home + avg_corners_away
    return base * (1 + alpha * abs(xg_diff))

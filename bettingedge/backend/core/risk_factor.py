"""
Facteur Risque composite — 5 dimensions, RF ∈ [0, 1].
RF pondère la mise recommandée par Kelly.
"""
import math


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def f_modele(n_similaires: int, scale: int = 50) -> float:
    """Volume historique de paris similaires. 0 = nouveau, 1 = bien calibré."""
    return 1 - math.exp(-n_similaires / scale)


def f_ev(ev: float) -> float:
    """
    EV optimal autour de 15%. Trop faible (bruit) ou trop fort (outlier) = suspicion.
    Pic à EV=0.15, retombe vers 0 si EV>0.50.
    """
    if ev <= 0:
        return 0.0
    low  = min(1.0, ev / 0.15)
    high = 1 - max(0.0, (ev - 0.15) / 0.35)
    return round(low * high, 4)


def f_variance(p: float, odds: float) -> float:
    """Variance du pari. Cote très haute = variance élevée = risque élevé."""
    denom = 1 + p * (1 - p) * (odds ** 2)
    if denom <= 0:
        return 0.0
    return round(1 / denom, 4)


def f_calib(brier_score: float, worst: float = 0.25) -> float:
    """Calibration du modèle. BS=0 → F=1, BS=worst → F=0."""
    return round(max(0.0, 1 - brier_score / worst), 4)


def f_clv(clv_mean: float) -> float:
    """Track record CLV. sigmoid centrée sur 0."""
    return round(_sigmoid(clv_mean * 20), 4)


def compute_rf(
    n_similaires: int,
    ev_value: float,
    p_estimated: float,
    odds: float,
    brier_score: float,
    clv_mean: float,
) -> float:
    """
    RF = 0.30×F_modèle + 0.20×F_ev + 0.15×F_variance + 0.20×F_calib + 0.15×F_clv
    """
    fm = f_modele(n_similaires)
    fe = f_ev(ev_value)
    fv = f_variance(p_estimated, odds)
    fc = f_calib(brier_score)
    fl = f_clv(clv_mean)

    rf = 0.30 * fm + 0.20 * fe + 0.15 * fv + 0.20 * fc + 0.15 * fl
    return round(min(max(rf, 0.0), 1.0), 4)


def rf_label(rf: float) -> str:
    """Interprétation lisible du score RF."""
    if rf >= 0.75:
        return "Élevé"
    if rf >= 0.50:
        return "Moyen"
    if rf >= 0.25:
        return "Faible"
    return "Très faible"

"""
Stratégie B — Value Betting sur marchés secondaires.
Niches foot : corners, BTTS, cartons.
Niches tennis : aces, double fautes, tie-breaks.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings
from backend.core.ev import value, ev
from backend.core.kelly import kelly_fraction, recommended_stake
from backend.core.risk_factor import compute_rf, rf_label
from backend.models.dixon_coles import predict_from_params, prob_btts
from backend.models.poisson import predict_over, lambda_aces, lambda_corners
from backend.models.markov_tennis import prob_set, expected_service_games
from backend.db.crud import get_model_params, get_portfolio


# ── Helpers ──────────────────────────────────────────────────────────────────

def _stake_info(p_estimated, odds_betclic, portfolio_name, db,
                n_similaires=0, brier_score=0.20, clv_mean=0.0):
    ev_val = ev(p_estimated, odds_betclic)
    rf = compute_rf(
        n_similaires=n_similaires,
        ev_value=ev_val,
        p_estimated=p_estimated,
        odds=odds_betclic,
        brier_score=brier_score,
        clv_mean=clv_mean,
    )
    kf = kelly_fraction(p_estimated, odds_betclic)
    portfolio = get_portfolio(db, portfolio_name)
    balance = portfolio.balance if portfolio else 1000.0
    stake = recommended_stake(balance, kf, rf)
    return {
        "ev": round(ev_val, 4),
        "ev_pct": round(ev_val * 100, 2),
        "kelly_fraction": kf,
        "rf": rf,
        "rf_label": rf_label(rf),
        "stake": stake,
        "balance": balance,
    }


# ── Niches Foot ───────────────────────────────────────────────────────────────

def calculate_corners(
    home_team: str,
    away_team: str,
    odds_over: float,
    threshold: float,
    db,
    portfolio: str = "B",
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet corners : P(corners > threshold) via Poisson.
    Requiert model_params : corners_home_{team}, corners_away_{team}.
    """
    params = get_model_params(db, "corners")
    ch = params.get(f"corners_home_{home_team}")
    ca = params.get(f"corners_away_{away_team}")

    if ch is None or ca is None:
        return {"error": f"Paramètres corners manquants pour {home_team}/{away_team}"}

    lam = lambda_corners(ch, ca)
    p_over = predict_over(lam, threshold)
    if p_over <= 0:
        return {"error": "Probabilité nulle"}

    odds_fair = round(1 / p_over, 3)
    val = value(odds_over, odds_fair)

    result = {
        "niche": "corners",
        "sport": "football",
        "description": f"Corners > {threshold}",
        "p_estimated": round(p_over, 4),
        "odds_fair": odds_fair,
        "odds_betclic": odds_over,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_over, odds_over, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


def calculate_btts(
    home_team: str,
    away_team: str,
    odds_btts: float,
    db,
    portfolio: str = "B",
    params: dict = None,
    gamma: float = 1.20,
    rho: float = -0.13,
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet BTTS via Dixon-Coles.
    """
    if params is None:
        params = get_model_params(db, "dixon_coles")

    try:
        matrix = predict_from_params(home_team, away_team, params, gamma, rho)
    except Exception as e:
        return {"error": f"Dixon-Coles : {e}"}

    p_btts = prob_btts(matrix)
    if p_btts <= 0:
        return {"error": "Probabilité BTTS nulle"}

    odds_fair = round(1 / p_btts, 3)
    val = value(odds_btts, odds_fair)

    result = {
        "niche": "btts",
        "sport": "football",
        "description": "Les deux équipes marquent",
        "p_estimated": round(p_btts, 4),
        "odds_fair": odds_fair,
        "odds_betclic": odds_btts,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_btts, odds_btts, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


def calculate_cards(
    referee: str,
    odds_over: float,
    threshold: float,
    db,
    portfolio: str = "B",
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet cartons via Poisson sur taux de cartons de l'arbitre.
    """
    params = get_model_params(db, "referee")
    cards_rate = params.get(f"cards_rate_{referee}")

    if cards_rate is None:
        return {"error": f"Taux de cartons manquant pour arbitre {referee}"}

    p_over = predict_over(cards_rate, threshold)
    odds_fair = round(1 / p_over, 3)
    val = value(odds_over, odds_fair)

    result = {
        "niche": "cartons",
        "sport": "football",
        "description": f"Cartons > {threshold} (arbitre {referee})",
        "p_estimated": round(p_over, 4),
        "odds_fair": odds_fair,
        "odds_betclic": odds_over,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_over, odds_over, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


# ── Niches Tennis ─────────────────────────────────────────────────────────────

def calculate_aces(
    player_a: str,
    player_b: str,
    surface: str,
    odds_over: float,
    threshold: float,
    db,
    best_of: int = 3,
    portfolio: str = "B",
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet aces via Poisson.
    Nécessite ace_rate_{joueur}_{surface} dans model_params.
    """
    params = get_model_params(db, "tennis")
    key_a = f"ace_rate_{player_a.lower()}_{surface}"
    key_b = f"ace_rate_{player_b.lower()}_{surface}"

    rate_a = params.get(key_a)
    rate_b = params.get(key_b)

    # Fallback sur taux moyen si joueur inconnu
    avg_ace = params.get(f"ace_rate_avg_{surface}", 0.08)
    rate_a = rate_a if rate_a is not None else avg_ace
    rate_b = rate_b if rate_b is not None else avg_ace

    # Approximation hold rate depuis ace rate (hold ≈ 0.60 + ace_rate * 0.5)
    hold_a = min(0.85, 0.60 + rate_a * 0.5)
    hold_b = min(0.85, 0.60 + rate_b * 0.5)

    e_games = expected_service_games(hold_a, hold_b, best_of)
    lam_a = lambda_aces(rate_a, e_games)
    lam_b = lambda_aces(rate_b, e_games)
    lam_total = lam_a + lam_b

    p_over = predict_over(lam_total, threshold)
    if p_over <= 0:
        return {"error": f"Probabilité aces > {threshold} nulle (λ={lam_total:.1f})"}
    odds_fair = round(1 / p_over, 3)
    val = value(odds_over, odds_fair)

    result = {
        "niche": "aces",
        "sport": "tennis",
        "surface": surface,
        "description": f"Aces > {threshold} ({player_a} vs {player_b}, {surface})",
        "p_estimated": round(p_over, 4),
        "lambda": round(lam_total, 2),
        "odds_fair": odds_fair,
        "odds_betclic": odds_over,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_over, odds_over, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


def calculate_double_faults(
    player_a: str,
    player_b: str,
    surface: str,
    odds_over: float,
    threshold: float,
    db,
    best_of: int = 3,
    portfolio: str = "B",
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet double fautes via Poisson.
    """
    params = get_model_params(db, "tennis")
    key_a = f"df_rate_{player_a.lower()}_{surface}"
    key_b = f"df_rate_{player_b.lower()}_{surface}"

    avg_df = params.get(f"df_rate_avg_{surface}", 0.03)
    rate_a = params.get(key_a, avg_df)
    rate_b = params.get(key_b, avg_df)

    hold_a = min(0.85, 0.60 + (params.get(f"ace_rate_{player_a.lower()}_{surface}", 0.08)) * 0.5)
    hold_b = min(0.85, 0.60 + (params.get(f"ace_rate_{player_b.lower()}_{surface}", 0.08)) * 0.5)

    e_games = expected_service_games(hold_a, hold_b, best_of)
    lam_total = (rate_a + rate_b) * e_games

    p_over = predict_over(lam_total, threshold)
    odds_fair = round(1 / p_over, 3)
    val = value(odds_over, odds_fair)

    result = {
        "niche": "double_faults",
        "sport": "tennis",
        "surface": surface,
        "description": f"Doubles fautes > {threshold} ({player_a} vs {player_b})",
        "p_estimated": round(p_over, 4),
        "lambda": round(lam_total, 2),
        "odds_fair": odds_fair,
        "odds_betclic": odds_over,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_over, odds_over, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


def calculate_tiebreak(
    player_a: str,
    player_b: str,
    surface: str,
    odds_yes: float,
    db,
    best_of: int = 3,
    portfolio: str = "B",
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Value bet tie-break (au moins 1 tie-break dans le match) via Markov.
    P(au moins 1 TB) ≈ 1 - P(aucun set n'arrive à 6-6)
    Approximation : P(TB dans un set) = P(6-6) = binom * p_set^6 * q_set^6 * C(12,6)
    """
    params = get_model_params(db, "tennis")
    avg_ace = params.get(f"ace_rate_avg_{surface}", 0.08)
    rate_a = params.get(f"ace_rate_{player_a.lower()}_{surface}", avg_ace)
    rate_b = params.get(f"ace_rate_{player_b.lower()}_{surface}", avg_ace)

    hold_a = min(0.85, 0.60 + rate_a * 0.5)
    hold_b = min(0.85, 0.60 + rate_b * 0.5)

    p_set_a = prob_set(hold_a, hold_b)
    q_set_a = 1 - p_set_a

    # P(set arrive à 6-6) approximation
    from math import comb
    p_66 = (p_set_a * q_set_a) ** 6 * comb(12, 6) * (p_set_a + q_set_a) ** 0  # normalisé
    p_66 = min(p_66, 0.35)  # borner l'approximation

    # P(au moins 1 TB sur 3 sets max)
    p_no_tb_per_set = 1 - p_66
    # E[sets] ≈ 2.5 en BO3 équilibré
    p_no_tb_match = p_no_tb_per_set ** 2.5
    p_tb = round(1 - p_no_tb_match, 4)

    odds_fair = round(1 / p_tb, 3)
    val = value(odds_yes, odds_fair)

    result = {
        "niche": "tiebreaks",
        "sport": "tennis",
        "surface": surface,
        "description": f"Au moins 1 tie-break ({player_a} vs {player_b})",
        "p_estimated": p_tb,
        "odds_fair": odds_fair,
        "odds_betclic": odds_yes,
        "value": round(val, 4),
        "value_pct": round(val * 100, 2),
        "is_positive": val > settings.ev_threshold_b,
    }
    result.update(_stake_info(p_tb, odds_yes, portfolio, db, n_similaires, brier_score, clv_mean))
    return result


# ── Dispatcher ────────────────────────────────────────────────────────────────

NICHE_CALCULATORS = {
    "corners": calculate_corners,
    "btts": calculate_btts,
    "cartons": calculate_cards,
    "aces": calculate_aces,
    "double_faults": calculate_double_faults,
    "tiebreaks": calculate_tiebreak,
}


def get_value_bets(
    candidates: list[dict],
    db,
    portfolio: str = "B",
) -> list[dict]:
    """
    Calcule les value bets pour une liste de candidats.
    Chaque candidat : {niche, sport, ...params spécifiques à la niche}
    Retourne la liste des value bets positifs triés par value décroissante.
    """
    results = []
    for c in candidates:
        niche = c.get("niche")
        fn = NICHE_CALCULATORS.get(niche)
        if not fn:
            continue

        # Injecter db et portfolio
        kwargs = {k: v for k, v in c.items() if k != "niche"}
        kwargs["db"] = db
        kwargs["portfolio"] = kwargs.get("portfolio", portfolio)

        try:
            result = fn(**kwargs)
            if "error" not in result and result.get("is_positive"):
                result["event"] = c.get("event", "")
                result["event_date"] = c.get("event_date", "")
                results.append(result)
        except Exception:
            continue

    results.sort(key=lambda x: x.get("value", 0), reverse=True)
    return results

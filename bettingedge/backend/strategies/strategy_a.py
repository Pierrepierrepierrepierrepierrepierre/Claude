"""
Stratégie A — Boosts EV (Super Boosts Betclic).
Pipeline : cote boost + cotes marché → de-vigging → consensus → EV → Kelly×RF → mise.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings
from backend.core.devig import devig, consensus
from backend.core.ev import ev, is_positive
from backend.core.kelly import kelly_fraction, recommended_stake
from backend.core.risk_factor import compute_rf, rf_label
from backend.db.crud import get_model_params, get_portfolio


def calculate_boost_ev(
    boost_odds: float,
    odds_1x2: list[float] = None,
    odds_ah: list[float] = None,
    odds_ou: list[float] = None,
    weights: list[float] = None,
    outcome_index: int = 0,
) -> dict:
    """
    Calcule l'EV d'un boost Betclic en utilisant le consensus multi-marchés
    comme estimateur de la vraie probabilité.

    outcome_index : index du résultat dans la liste de cotes 1X2 (0=dom, 1=nul, 2=ext)
                    ou 0 pour les marchés AH/OU à deux issues.
    """
    probs = consensus(
        odds_1x2=odds_1x2,
        odds_ah=odds_ah,
        odds_ou=odds_ou,
        weights=weights,
    )
    if not probs:
        return {"error": "Pas assez de données pour calculer le consensus"}

    # Récupérer la probabilité de l'issue boostée
    if outcome_index >= len(probs):
        return {"error": f"outcome_index {outcome_index} hors de portée ({len(probs)} issues)"}

    p_consensus = probs[outcome_index]
    ev_value = ev(p_consensus, boost_odds)
    threshold = settings.ev_threshold_a  # défaut 0.03

    return {
        "p_consensus": round(p_consensus, 4),
        "boost_odds": boost_odds,
        "ev": round(ev_value, 4),
        "ev_pct": round(ev_value * 100, 2),
        "is_positive": is_positive(ev_value, threshold),
        "threshold_used": threshold,
        "all_probs": probs,
    }


def calculate_stake(
    boost_odds: float,
    p_consensus: float,
    portfolio_name: str,
    db,
    n_similaires: int = 0,
    brier_score: float = 0.20,
    clv_mean: float = 0.0,
) -> dict:
    """
    Calcule la mise recommandée pour un boost EV+ donné.
    Utilise Kelly × RF, plafonné à max_stake_pct du portefeuille.
    """
    portfolio = get_portfolio(db, portfolio_name)
    if not portfolio:
        return {"error": f"Portefeuille '{portfolio_name}' introuvable"}

    ev_value = ev(p_consensus, boost_odds)

    rf = compute_rf(
        n_similaires=n_similaires,
        ev_value=ev_value,
        p_estimated=p_consensus,
        odds=boost_odds,
        brier_score=brier_score,
        clv_mean=clv_mean,
    )

    kf = kelly_fraction(p_consensus, boost_odds)
    stake = recommended_stake(
        portfolio=portfolio.balance,
        kelly_f=kf,
        rf=rf,
    )

    return {
        "portfolio": portfolio_name,
        "balance": portfolio.balance,
        "kelly_fraction": kf,
        "rf": rf,
        "rf_label": rf_label(rf),
        "stake": stake,
        "stake_pct": round(stake / portfolio.balance * 100, 2) if portfolio.balance > 0 else 0,
    }


def get_boost_opportunities(db, odds_records: list[dict]) -> list[dict]:
    """
    Filtre les cotes Betclic pour trouver les boosts EV+.
    odds_records : liste de dicts depuis odds_history, chaque record contient
        { event, market_type, odds_home, odds_draw, odds_away, ... }
    Retourne les opportunités EV+ triées par EV décroissant.
    """
    opportunities = []

    for record in odds_records:
        # On n'analyse que les cotes marquées comme boost
        if not record.get("is_boost"):
            continue

        boost_odds = record.get("boost_odds")
        if not boost_odds:
            continue

        # Construire les cotes de marché normales
        odds_1x2 = None
        if record.get("odds_home") and record.get("odds_draw") and record.get("odds_away"):
            odds_1x2 = [record["odds_home"], record["odds_draw"], record["odds_away"]]

        odds_ah = None
        if record.get("odds_ah_home") and record.get("odds_ah_away"):
            odds_ah = [record["odds_ah_home"], record["odds_ah_away"]]

        odds_ou = None
        if record.get("odds_ou_over") and record.get("odds_ou_under"):
            odds_ou = [record["odds_ou_over"], record["odds_ou_under"]]

        outcome_index = record.get("outcome_index", 0)

        result = calculate_boost_ev(
            boost_odds=boost_odds,
            odds_1x2=odds_1x2,
            odds_ah=odds_ah,
            odds_ou=odds_ou,
            outcome_index=outcome_index,
        )

        if result.get("is_positive"):
            opportunities.append({
                "event": record.get("event_name", ""),
                "market": record.get("market_type", ""),
                "sport": record.get("sport", ""),
                "boost_odds": boost_odds,
                "normal_odds": record.get("normal_odds"),
                "p_consensus": result["p_consensus"],
                "ev": result["ev"],
                "ev_pct": result["ev_pct"],
                "event_date": record.get("event_date"),
            })

    opportunities.sort(key=lambda x: x["ev"], reverse=True)
    return opportunities

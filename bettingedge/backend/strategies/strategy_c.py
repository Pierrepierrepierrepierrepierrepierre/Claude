"""
Stratégie C — CLV Tracker.
Suit la Closing Line Value comme KPI de santé du modèle.
CLV > 0 sur durée = edge prouvé (le modèle bat la clôture du marché).
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from backend.core.ev import clv as compute_clv
from backend.db.crud import get_bets


def compute_clv_stats(db, strategy: str = "C") -> dict:
    """
    Calcule les stats CLV pour un portefeuille donné.
    Retourne CLV par pari, CLV moyen, z-score, interprétation.
    """
    bets = get_bets(db, strategy=strategy, resolved=True)

    clv_values = []
    bet_details = []

    for bet in bets:
        if bet.odds_close and bet.odds_close > 0 and bet.odds_taken:
            clv_val = compute_clv(bet.odds_taken, bet.odds_close)
            clv_values.append(clv_val)
            bet_details.append({
                "id": bet.id,
                "market": bet.market,
                "sport": bet.sport,
                "odds_taken": bet.odds_taken,
                "odds_close": bet.odds_close,
                "clv": round(clv_val, 4),
                "clv_pct": round(clv_val * 100, 2),
                "result": bet.result,
                "stake": bet.stake,
                "resolved_at": bet.resolved_at,
            })

    n = len(clv_values)
    if n == 0:
        return {
            "strategy": strategy,
            "n_bets": 0,
            "clv_mean": 0.0,
            "clv_std": 0.0,
            "z_score": 0.0,
            "is_significant": False,
            "interpretation": "Pas encore de données",
            "bets": [],
        }

    clv_mean = sum(clv_values) / n
    variance = sum((x - clv_mean) ** 2 for x in clv_values) / n if n > 1 else 0.0
    clv_std = math.sqrt(variance)
    z_score = (clv_mean / (clv_std / math.sqrt(n))) if clv_std > 0 else 0.0

    is_significant = z_score > 1.645  # seuil 95% unilatéral
    if z_score > 2.33:
        interp = "Edge très significatif (p < 1%)"
    elif is_significant:
        interp = "Edge prouvé (p < 5%)"
    elif z_score > 1.0:
        interp = "Tendance positive, pas encore significatif"
    elif z_score < 0:
        interp = "CLV négatif — modèle à recalibrer"
    else:
        interp = "Insuffisant pour conclure"

    return {
        "strategy": strategy,
        "n_bets": n,
        "clv_mean": round(clv_mean, 4),
        "clv_mean_pct": round(clv_mean * 100, 2),
        "clv_std": round(clv_std, 4),
        "z_score": round(z_score, 3),
        "is_significant": is_significant,
        "interpretation": interp,
        "bets": sorted(bet_details, key=lambda x: x.get("resolved_at", ""), reverse=True),
    }


def detect_line_movements(db, threshold: float = 0.05) -> list[dict]:
    """
    Détecte les mouvements de cotes significatifs (baisse > threshold) dans odds_history.
    Un mouvement sharp signifie que les parieurs professionnels ont misé sur cette issue.
    Retourne les événements avec mouvement détecté, triés par amplitude décroissante.
    """
    from backend.db.models import OddsHistory
    from sqlalchemy import func
    from datetime import datetime, timedelta

    cutoff = (datetime.utcnow() - timedelta(hours=48)).isoformat()

    # Récupérer toutes les cotes des 48 dernières heures groupées par event_id + market_type
    rows = (
        db.query(OddsHistory)
        .filter(OddsHistory.scraped_at >= cutoff)
        .order_by(OddsHistory.event_id, OddsHistory.market_type, OddsHistory.scraped_at)
        .all()
    )

    # Grouper par (event_id, market_type)
    groups = {}
    for r in rows:
        key = (r.event_id, r.market_type)
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    movements = []
    for (event_id, market_type), records in groups.items():
        if len(records) < 2:
            continue

        first = records[0]
        last = records[-1]

        # Comparer cotes home (ou la première cote disponible)
        def get_primary_odds(rec):
            return rec.odds_home or rec.odds_ou_over or rec.boost_odds

        odds_open = get_primary_odds(first)
        odds_close = get_primary_odds(last)

        if not odds_open or not odds_close or odds_open <= 1:
            continue

        # Baisse de cote = signal haussier sur l'issue (plus de mises → cote baisse)
        variation = (odds_close - odds_open) / odds_open

        if abs(variation) >= threshold:
            movements.append({
                "event_id": event_id,
                "event_name": last.event_name or event_id,
                "market_type": market_type,
                "sport": last.sport,
                "odds_open": odds_open,
                "odds_current": odds_close,
                "variation_pct": round(variation * 100, 2),
                "direction": "baisse" if variation < 0 else "hausse",
                "is_sharp": variation < -threshold,
                "n_snapshots": len(records),
                "last_scraped": last.scraped_at,
            })

    movements.sort(key=lambda x: abs(x["variation_pct"]), reverse=True)
    return movements

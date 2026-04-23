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


# ── Auto-résolution des paris terminés ─────────────────────────────────────

def _outcome_won(niche: str, outcome: str, score_home: int, score_away: int) -> bool | None:
    """
    Détermine si un pari a gagné selon (niche, outcome, score réel).
    Renvoie True/False, ou None si on ne sait pas trancher (niche inconnue).
    """
    total = score_home + score_away
    home_won = score_home > score_away
    away_won = score_home < score_away
    draw     = score_home == score_away
    btts     = score_home >= 1 and score_away >= 1

    n = (niche or "").lower()
    o = (outcome or "").lower()

    # 1X2 (peut venir comme niche='1x2_home' OU niche='1x2' + outcome='home')
    if n in ("1x2_home", "1x2") and (n == "1x2_home" or o == "home"):
        return home_won
    if n in ("1x2_draw", "1x2") and (n == "1x2_draw" or o in ("draw", "nul", "n", "x")):
        return draw
    if n in ("1x2_away", "1x2") and (n == "1x2_away" or o == "away"):
        return away_won

    # BTTS
    if n.startswith("btts_yes"): return btts
    if n.startswith("btts_no"):  return not btts

    # Over / Under (le seuil est dans le nom : over_2.5)
    if n.startswith("over_"):
        try:
            thr = float(n.split("_", 1)[1])
            return total > thr
        except Exception:
            return None
    if n.startswith("under_"):
        try:
            thr = float(n.split("_", 1)[1])
            return total <= thr
        except Exception:
            return None

    return None


def _closing_odds_for(closing: dict, niche: str, outcome: str) -> float | None:
    """Sélectionne la cote de clôture pertinente (Pinnacle 1X2)."""
    if not closing:
        return None
    n = (niche or "").lower()
    o = (outcome or "").lower()
    if "home" in n or o == "home": return closing.get("pinnacle_home")
    if "draw" in n or o in ("draw", "nul"): return closing.get("pinnacle_draw")
    if "away" in n or o == "away": return closing.get("pinnacle_away")
    # Pour BTTS / OU on n'a pas de cote close Pinnacle dans le helper actuel
    return None


def auto_resolve_pending_bets(db, max_bets: int = 50) -> dict:
    """
    Pour chaque pari open dont le match est passé, tente de le résoudre
    automatiquement via football-data.co.uk :
      1. Lit features_json (event_name, league, event_date, outcome)
      2. get_pinnacle_closing → score réel + cotes closing
      3. Détermine win/loss selon niche
      4. Appelle resolve_bet → CLV calculé automatiquement

    Renvoie {n_resolved, n_skipped_no_data, n_skipped_unknown_outcome, errors}
    """
    import json
    from datetime import datetime, timezone, timedelta
    from backend.db.models import Bet
    from backend.db.crud import resolve_bet
    from backend.core.closing_odds import get_pinnacle_closing
    from backend.core.team_mapping import parse_event_name

    now_iso = datetime.now(timezone.utc).isoformat()
    open_bets = (
        db.query(Bet)
        .filter(Bet.result.is_(None))
        .order_by(Bet.created_at.asc())
        .limit(max_bets)
        .all()
    )

    n_resolved = n_no_data = n_unknown = 0
    errors: list[str] = []

    for bet in open_bets:
        try:
            feats = json.loads(bet.features_json or "{}")
            event_name = feats.get("event_name") or ""
            event_date = feats.get("event_date") or ""
            league_hint = feats.get("league") or bet.league or ""
            outcome = feats.get("outcome") or ""

            # Skip si le match n'a pas encore eu lieu (event_date dans le futur)
            if event_date and event_date > now_iso:
                n_no_data += 1
                continue

            home, away = parse_event_name(event_name)
            if not home or not away:
                n_no_data += 1
                continue

            closing = get_pinnacle_closing(home, away, league_hint, event_date)
            if not closing or not closing.get("score"):
                n_no_data += 1
                continue

            # Score "H-A"
            try:
                sh, sa = (int(x) for x in closing["score"].split("-"))
            except Exception:
                n_no_data += 1
                continue

            niche = bet.market or ""  # market = la niche du pari (1x2_home, btts_no...)
            won = _outcome_won(niche, outcome, sh, sa)
            if won is None:
                n_unknown += 1
                continue

            # Cote close = Pinnacle pour 1X2, sinon on garde odds_taken (pas de CLV)
            odds_close = _closing_odds_for(closing, niche, outcome) or bet.odds_taken
            resolve_bet(db, bet.id, 1 if won else 0, odds_close)
            n_resolved += 1
        except Exception as e:
            errors.append(f"bet#{bet.id}: {e}")

    return {
        "n_resolved":       n_resolved,
        "n_no_data":        n_no_data,    # match pas encore en BDD football-data
        "n_unknown_outcome": n_unknown,    # niche non gérée
        "errors":           errors[:10],
        "n_processed":      len(open_bets),
    }

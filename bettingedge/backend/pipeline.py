"""
Pipeline d'analyse — cœur de BettingEdge.
Tourne après chaque scraping Betclic.
Pour chaque match du jour :
  - Football : Dixon-Coles → P(1X2), P(BTTS), P(Over/Under), P(corners)
  - Tennis   : Markov → P(match), Poisson → P(aces > N), P(tie-break)
  - Compare avec cotes Betclic → value bets + recommandations
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from backend.db.models import OddsHistory, Recommendation
from backend.db.crud import get_model_params, get_portfolio
from backend.models.dixon_coles import predict_from_params, prob_home_win, prob_draw, prob_away_win, prob_btts, prob_over
from backend.models.poisson import predict_over, lambda_aces, lambda_corners
from backend.models.markov_tennis import prob_match, prob_set, expected_service_games
from backend.core.devig import devig, consensus
from backend.core.ev import ev as compute_ev, value as compute_value
from backend.core.kelly import kelly_fraction, recommended_stake
from backend.core.risk_factor import compute_rf, rf_label
from backend.core.team_mapping import resolve_team, resolve_player, parse_event_name
from config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stake(p, odds, portfolio_balance, n_simi=0, brier=0.20, clv=0.0):
    ev_val = compute_ev(p, odds)
    rf = compute_rf(n_simi, ev_val, p, odds, brier, clv)
    kf = kelly_fraction(p, odds)
    stake = recommended_stake(portfolio_balance, kf, rf)
    return ev_val, rf, rf_label(rf), stake


def _save_recommendation(db: Session, reco: dict):
    """Upsert une recommandation (event_id + niche = clé unique)."""
    existing = db.query(Recommendation).filter_by(
        event_id=reco["event_id"],
        niche=reco["niche"],
        strategy=reco["strategy"],
    ).first()
    if existing:
        for k, v in reco.items():
            setattr(existing, k, v)
    else:
        db.add(Recommendation(**reco))


# ── Football ──────────────────────────────────────────────────────────────────

def analyze_football(event: OddsHistory, params: dict, balance_b: float, db: Session) -> list[dict]:
    """
    Analyse un match de foot via Dixon-Coles.
    Génère des recommandations pour : 1X2, BTTS, Over/Under 2.5.
    """
    recos = []
    home_raw, away_raw = parse_event_name(event.event_name)
    if not home_raw or not away_raw:
        return recos

    home_key, home_conf = resolve_team(home_raw, params)
    away_key, away_conf = resolve_team(away_raw, params)
    confidence = "high" if home_conf == "high" and away_conf == "high" else \
                 "medium" if "low" not in (home_conf, away_conf) else "low"

    gamma = params.get("gamma", 1.20)
    rho   = params.get("rho", -0.13)

    # Vérifier que les paramètres existent (au moins att)
    if f"att_{home_key}" not in params or f"att_{away_key}" not in params:
        # Paramètres manquants → on ne peut pas analyser ce match
        return recos

    try:
        matrix = predict_from_params(home_key, away_key, params, gamma, rho)
    except Exception:
        return recos

    p_home = prob_home_win(matrix)
    p_draw = prob_draw(matrix)
    p_away = prob_away_win(matrix)
    p_btts = prob_btts(matrix)
    p_over = prob_over(matrix, 2.5)

    base = {
        "event_id":   event.event_id,
        "event_name": event.event_name,
        "home_team":  home_raw,
        "away_team":  away_raw,
        "event_date": event.event_date,
        "sport":      "football",
        "league":     event.league or "",
        "strategy":   "B",
        "confidence": confidence,
        "generated_at": _now(),
    }

    # ── 1X2 : trouver la meilleure issue si value+ ──
    for p_est, odds_betclic, outcome_name, outcome_idx in [
        (p_home, event.odds_home, "Victoire domicile", 0),
        (p_draw, event.odds_draw, "Nul",               1),
        (p_away, event.odds_away, "Victoire extérieur", 2),
    ]:
        if not odds_betclic or p_est <= 0:
            continue
        odds_fair = round(1 / p_est, 3)
        val = compute_value(odds_betclic, odds_fair)

        # Bug 2 mitigation : DC simplifié sur-estime les nuls → seuil EV plus haut
        threshold = settings.ev_threshold_b
        if outcome_idx == 1:
            threshold += settings.ev_threshold_draw_extra

        if val <= threshold:
            continue

        ev_val_pre, _, _, _ = _stake(p_est, odds_betclic, balance_b)
        # Bug 3 mitigation : EV anormal (>50%) → modèle suspect, on skippe
        if ev_val_pre > settings.ev_cap:
            continue

        ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
        recos.append({**base,
            "niche":       "1x2",
            "description": f"{outcome_name} ({event.event_name})",
            "p_estimated": round(p_est, 4),
            "odds_fair":   odds_fair,
            "odds_betclic": odds_betclic,
            "value":       round(val, 4),
            "ev":          round(ev_val, 4),
            "rf":          rf,
            "rf_label":    rf_lbl,
            "stake_recommended": stake,
        })

    # ── BTTS ──
    if event.odds_draw and p_btts > 0:
        # Betclic ne stocke pas les cotes BTTS dans notre schéma pour l'instant
        # On utilise une cote estimée si on avait une référence ; skip si pas de cote BTTS
        pass

    # ── Over 2.5 ──
    if event.odds_ou_over and p_over > 0:
        odds_fair_over = round(1 / p_over, 3)
        val = compute_value(event.odds_ou_over, odds_fair_over)
        if val > settings.ev_threshold_b:
            ev_val, rf, rf_lbl, stake = _stake(p_over, event.odds_ou_over, balance_b)
            if ev_val <= settings.ev_cap:
                recos.append({**base,
                    "niche":       "over25",
                    "description": f"Plus de 2.5 buts ({event.event_name})",
                    "p_estimated": round(p_over, 4),
                    "odds_fair":   odds_fair_over,
                    "odds_betclic": event.odds_ou_over,
                    "value":       round(val, 4),
                    "ev":          round(ev_val, 4),
                    "rf":          rf,
                    "rf_label":    rf_lbl,
                    "stake_recommended": stake,
                })

    # ── Boost Strategy A ──
    if event.is_boost and event.boost_odds:
        # Utiliser le consensus 1X2 dévigué comme p_consensus
        if event.odds_home and event.odds_draw and event.odds_away:
            probs = devig([event.odds_home, event.odds_draw, event.odds_away])
            if probs:
                outcome_idx = event.outcome_index or 0
                p_consensus = probs[outcome_idx] if outcome_idx < len(probs) else probs[0]
                ev_boost = compute_ev(p_consensus, event.boost_odds)
                if ev_boost > settings.ev_threshold_a:
                    balance_a = get_portfolio(db, "A")
                    balance_a = balance_a.balance if balance_a else 1000.0
                    ev_val, rf, rf_lbl, stake = _stake(p_consensus, event.boost_odds, balance_a)
                    recos.append({**base,
                        "strategy":    "A",
                        "niche":       "boost",
                        "description": f"Super Boost ({event.event_name})",
                        "p_estimated": round(p_consensus, 4),
                        "odds_fair":   round(1/p_consensus, 3),
                        "odds_betclic": event.boost_odds,
                        "value":       round(compute_value(event.boost_odds, 1/p_consensus), 4),
                        "ev":          round(ev_boost, 4),
                        "rf":          rf,
                        "rf_label":    rf_lbl,
                        "stake_recommended": stake,
                    })

    return recos


# ── Tennis ────────────────────────────────────────────────────────────────────

def analyze_tennis(event: OddsHistory, params: dict, balance_b: float, db: Session) -> list[dict]:
    """
    Analyse un match de tennis via Markov + Poisson.
    Génère : 1X2 (vainqueur), aces over/under.
    """
    recos = []
    player_a_raw, player_b_raw = parse_event_name(event.event_name)
    if not player_a_raw or not player_b_raw:
        return recos

    pa_key, pa_conf = resolve_player(player_a_raw, params)
    pb_key, pb_conf = resolve_player(player_b_raw, params)
    confidence = "high" if pa_conf == "high" and pb_conf == "high" else \
                 "medium" if "low" not in (pa_conf, pb_conf) else "low"

    # Détecter la surface depuis la ligue/compétition
    surface = "hard"  # défaut
    league_lower = (event.league or "").lower()
    if "clay" in league_lower or "terre" in league_lower or "roland" in league_lower:
        surface = "clay"
    elif "grass" in league_lower or "wimbledon" in league_lower or "gazon" in league_lower:
        surface = "grass"

    # Bug 1 fix : si AUCUN des deux joueurs n'a d'ace_rate connu, on n'a aucun
    # signal différentiel → P=50/50 produirait du faux value sur l'outsider.
    # On skippe complètement le match dans ce cas.
    rate_a_known = f"ace_rate_{pa_key}_{surface}" in params
    rate_b_known = f"ace_rate_{pb_key}_{surface}" in params
    if not (rate_a_known or rate_b_known):
        return recos

    avg_ace = params.get(f"ace_rate_avg_{surface}", 0.08)
    rate_a = params.get(f"ace_rate_{pa_key}_{surface}", avg_ace)
    rate_b = params.get(f"ace_rate_{pb_key}_{surface}", avg_ace)

    hold_a = min(0.85, 0.60 + rate_a * 0.5)
    hold_b = min(0.85, 0.60 + rate_b * 0.5)

    base = {
        "event_id":   event.event_id,
        "event_name": event.event_name,
        "player_a":   player_a_raw,
        "player_b":   player_b_raw,
        "event_date": event.event_date,
        "sport":      "tennis",
        "league":     event.league or "",
        "surface":    surface,
        "strategy":   "B",
        "confidence": confidence,
        "generated_at": _now(),
    }

    # ── Vainqueur du match ──
    if event.odds_home and event.odds_away:
        p_a_wins = prob_match(hold_a, hold_b, best_of=3)
        p_b_wins = 1 - p_a_wins

        for p_est, odds_betclic, desc in [
            (p_a_wins, event.odds_home, f"{player_a_raw} gagne"),
            (p_b_wins, event.odds_away, f"{player_b_raw} gagne"),
        ]:
            if p_est <= 0:
                continue
            odds_fair = round(1 / p_est, 3)
            val = compute_value(odds_betclic, odds_fair)
            if val > settings.ev_threshold_b:
                ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
                if ev_val <= settings.ev_cap:
                    recos.append({**base,
                        "niche":       "tennis_winner",
                        "description": f"{desc} ({event.event_name})",
                        "p_estimated": round(p_est, 4),
                        "odds_fair":   odds_fair,
                        "odds_betclic": odds_betclic,
                        "value":       round(val, 4),
                        "ev":          round(ev_val, 4),
                        "rf":          rf,
                        "rf_label":    rf_lbl,
                        "stake_recommended": stake,
                    })

    # ── Aces Over/Under ── (si cote O/U disponible)
    if event.odds_ou_over and event.odds_ou_under:
        e_games = expected_service_games(hold_a, hold_b, best_of=3)
        lam_a = lambda_aces(rate_a, e_games)
        lam_b = lambda_aces(rate_b, e_games)
        lam_total = lam_a + lam_b

        # Seuil : on essaie 20.5 et 22.5
        for threshold in [20.5, 22.5]:
            p_over_aces = predict_over(lam_total, threshold)
            p_under_aces = 1 - p_over_aces

            if p_over_aces <= 0.01 or p_under_aces <= 0.01:
                continue

            for p_est, odds_betclic, desc in [
                (p_over_aces,  event.odds_ou_over,  f"Aces > {threshold}"),
                (p_under_aces, event.odds_ou_under, f"Aces < {threshold}"),
            ]:
                odds_fair = round(1 / p_est, 3)
                val = compute_value(odds_betclic, odds_fair)
                if val > settings.ev_threshold_b:
                    ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
                    if ev_val <= settings.ev_cap:
                        recos.append({**base,
                            "niche":       f"aces_{threshold}",
                            "description": f"{desc} ({event.event_name})",
                            "p_estimated": round(p_est, 4),
                            "odds_fair":   odds_fair,
                            "odds_betclic": odds_betclic,
                            "value":       round(val, 4),
                            "ev":          round(ev_val, 4),
                            "rf":          rf,
                            "rf_label":    rf_lbl,
                            "stake_recommended": stake,
                        })

    return recos


# ── Boosts sans match associé (Strategy A) ───────────────────────────────────

def analyze_boost_standalone(event: OddsHistory, balance_a: float) -> list[dict]:
    """
    Analyse un boost sans cotes de marché (pas de 1X2 de référence).
    Utilise uniquement la cote normale vs boost.
    """
    if not event.boost_odds or not event.normal_odds:
        return []

    # Cote normale → p implicite
    p_impl = 1 / event.normal_odds
    ev_val = compute_ev(p_impl, event.boost_odds)

    if ev_val <= settings.ev_threshold_a:
        return []

    rf = compute_rf(0, ev_val, p_impl, event.boost_odds, 0.20, 0.0)
    kf = kelly_fraction(p_impl, event.boost_odds)
    stake = recommended_stake(balance_a, kf, rf)

    return [{
        "event_id":    event.event_id,
        "event_name":  event.event_name,
        "event_date":  event.event_date,
        "sport":       event.sport or "football",
        "strategy":    "A",
        "niche":       "boost",
        "description": f"Super Boost — {event.event_name}",
        "p_estimated": round(p_impl, 4),
        "odds_fair":   round(event.normal_odds, 3),
        "odds_betclic": event.boost_odds,
        "value":       round(compute_value(event.boost_odds, event.normal_odds), 4),
        "ev":          round(ev_val, 4),
        "rf":          rf,
        "rf_label":    rf_label(rf),
        "stake_recommended": stake,
        "confidence":  "medium",
        "generated_at": _now(),
    }]


# ── Runner principal ──────────────────────────────────────────────────────────

def run_pipeline(
    db: Session,
    horizon_hours: int = 48,
    top_k: int = 20,
) -> int:
    """
    Tourne le pipeline d'analyse sur tous les matchs scrapés < 24h ET dont
    `event_date` tombe dans la fenêtre [now, now + horizon_hours].

    À la fin, on garde au plus `top_k` recommandations triées par EV
    décroissante (les meilleures de la journée). Les anciennes recos hors
    top sont supprimées de la BDD.

    Retourne le nombre de recommandations conservées.
    """
    now = datetime.now(timezone.utc)
    scrape_cutoff = (now - timedelta(hours=24)).isoformat()
    horizon_end = (now + timedelta(hours=horizon_hours)).isoformat()
    horizon_start = now.isoformat()

    # Événements scrapés récemment ET dont event_date est dans la fenêtre
    events_q = db.query(OddsHistory).filter(OddsHistory.scraped_at >= scrape_cutoff)
    events = []
    for e in events_q.all():
        # Garder si event_date manquant (sécurité) ou dans la fenêtre [now, now+horizon]
        if not e.event_date:
            events.append(e); continue
        try:
            # event_date au format ISO ou "YYYY-MM-DDTHH:MM:SS"
            ed = e.event_date if "T" in e.event_date else e.event_date + "T00:00:00"
            if horizon_start <= ed <= horizon_end:
                events.append(e)
        except Exception:
            events.append(e)

    if not events:
        return 0

    dc_params   = get_model_params(db, "dixon_coles")
    tennis_params = get_model_params(db, "tennis")

    port_a = get_portfolio(db, "A")
    port_b = get_portfolio(db, "B")
    balance_a = port_a.balance if port_a else 1000.0
    balance_b = port_b.balance if port_b else 1000.0

    candidate_recos: list[dict] = []

    for event in events:
        try:
            recos = []

            if event.is_boost and event.market_type == "BOOST":
                recos = analyze_boost_standalone(event, balance_a)

            elif event.sport == "football" and event.market_type == "1X2":
                recos = analyze_football(event, dc_params, balance_b, db)

            elif event.sport == "tennis" and event.market_type == "1X2":
                recos = analyze_tennis(event, tennis_params, balance_b, db)

            candidate_recos.extend(recos)

        except Exception as e:
            print(f"Pipeline [WARN] {event.event_name}: {e}")
            continue

    # Tri par EV décroissante, on garde les top_k
    candidate_recos.sort(key=lambda r: r.get("ev", 0), reverse=True)
    selected = candidate_recos[:top_k]

    # Wipe les anciennes recos pour ne garder que la sélection actuelle
    # (le pipeline reproduit la sélection complète à chaque run, pas besoin
    # d'upsert — un même match peut avoir plusieurs value bets sur des
    # outcomes différents dans la même niche "1x2")
    db.query(Recommendation).delete()
    db.commit()
    for reco in selected:
        db.add(Recommendation(**reco))
    db.commit()
    n_kept = len(selected)
    print(f"Pipeline terminé : {len(candidate_recos)} candidates -> {n_kept} recos top-{top_k} "
          f"(fenêtre {horizon_hours}h, {len(events)} événements analysés)")
    return n_kept


if __name__ == "__main__":
    from backend.db.database import SessionLocal
    db = SessionLocal()
    n = run_pipeline(db)
    db.close()
    print(f"{n} recommandations générées")

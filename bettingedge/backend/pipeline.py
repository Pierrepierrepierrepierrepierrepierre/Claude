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


def _league_key(betclic_league: str) -> str:
    """Mappe un nom de ligue Betclic vers la clé utilisée dans la blacklist."""
    n = (betclic_league or "").lower()
    if "premier league" in n or "england" in n or "anglais" in n: return "premier_league"
    if "ligue 1" in n: return "ligue1"
    if "ligue 2" in n: return "ligue2"
    if "liga" in n and "europa" not in n: return "liga"
    if "serie a" in n: return "serie_a"
    if "bundes" in n: return "bundesliga"
    return ""


def _is_blacklisted(niche_outcome: str, league_key: str) -> bool:
    """Vérifie si la combo niche × ligue est dans la blacklist (backtest insight)."""
    if not league_key:
        return False
    return f"{niche_outcome}:{league_key}" in (settings.blacklist_combos or [])


def _is_disabled_niche(niche: str) -> bool:
    """Niches bannies globalement (ex: 'under_2.5' → DC sous-prédit les buts)."""
    return any(niche.startswith(p) for p in (settings.disabled_niches or []))


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
    # Seuil O/U dynamique (Betclic peut renvoyer 1.5/2.5/3.5 selon le match)
    ou_thr = event.ou_threshold or 2.5
    p_over = prob_over(matrix, ou_thr)

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

    league_key = _league_key(event.league)

    # ── 1X2 : trouver la meilleure issue si value+ ──
    for p_est, odds_betclic, outcome_name, outcome_label in [
        (p_home, event.odds_home, "Victoire domicile",   "1x2_home"),
        (p_draw, event.odds_draw, "Nul",                 "1x2_draw"),
        (p_away, event.odds_away, "Victoire extérieur",  "1x2_away"),
    ]:
        if not odds_betclic or p_est <= 0:
            continue
        # Blacklist combo niche × ligue (perdants identifiés au backtest)
        if _is_blacklisted(outcome_label, league_key):
            continue

        odds_fair = round(1 / p_est, 3)
        val = compute_value(odds_betclic, odds_fair)

        # DC simplifié sur-estime les nuls → seuil EV plus haut pour Nul
        threshold = settings.ev_threshold_b
        if outcome_label == "1x2_draw":
            threshold += settings.ev_threshold_draw_extra

        if val <= threshold:
            continue

        ev_val_pre, _, _, _ = _stake(p_est, odds_betclic, balance_b)
        # EV anormal (>50%) → modèle suspect, on skippe
        if ev_val_pre > settings.ev_cap:
            continue

        ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
        recos.append({**base,
            "niche":       outcome_label,
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

    # ── BTTS Yes / No ──
    for p_est, odds_betclic, desc, label in [
        (p_btts,        event.odds_btts_yes, "Les 2 marquent : Oui", "btts_yes"),
        (1.0 - p_btts,  event.odds_btts_no,  "Les 2 marquent : Non", "btts_no"),
    ]:
        if not odds_betclic or p_est <= 0:
            continue
        odds_fair = round(1 / p_est, 3)
        val = compute_value(odds_betclic, odds_fair)
        if val <= settings.ev_threshold_b:
            continue
        ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
        if ev_val > settings.ev_cap:
            continue
        recos.append({**base,
            "niche":       label,
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

    # ── Over / Under buts (seuil dynamique 1.5 / 2.5 / 3.5) ──
    thr_label = str(ou_thr).replace(".", ",")
    for p_est, odds_betclic, desc, niche in [
        (p_over,        event.odds_ou_over,  f"Plus de {thr_label} buts",  f"over_{ou_thr}"),
        (1.0 - p_over,  event.odds_ou_under, f"Moins de {thr_label} buts", f"under_{ou_thr}"),
    ]:
        if not odds_betclic or p_est <= 0:
            continue
        # Niche désactivée globalement (under_ : DC sous-prédit, ROI -7% en backtest)
        if _is_disabled_niche(niche):
            continue
        if _is_blacklisted(niche, league_key):
            continue
        odds_fair = round(1 / p_est, 3)
        val = compute_value(odds_betclic, odds_fair)
        if val <= settings.ev_threshold_b:
            continue
        ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
        if ev_val > settings.ev_cap:
            continue
        recos.append({**base,
            "niche":       niche,
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

    # ── Aces Over/Under (page-match Betclic, seuil dynamique) ──────────────
    # Betclic expose souvent que le côté Over → on génère la reco quand même.
    if event.odds_aces_over and event.aces_threshold:
        e_games = expected_service_games(hold_a, hold_b, best_of=3)
        lam_a = lambda_aces(rate_a, e_games)
        lam_b = lambda_aces(rate_b, e_games)
        lam_total = lam_a + lam_b
        threshold = event.aces_threshold

        p_over_aces  = predict_over(lam_total, threshold)
        p_under_aces = 1 - p_over_aces
        thr_label = str(threshold).replace(".", ",")

        outcomes = [(p_over_aces, event.odds_aces_over, f"Aces : + de {thr_label}", f"aces_over_{threshold}")]
        if event.odds_aces_under:  # Under uniquement si dispo
            outcomes.append((p_under_aces, event.odds_aces_under, f"Aces : - de {thr_label}", f"aces_under_{threshold}"))

        for p_est, odds_betclic, desc, niche in outcomes:
            if p_est <= 0.01:
                continue
            odds_fair = round(1 / p_est, 3)
            val = compute_value(odds_betclic, odds_fair)
            if val <= settings.ev_threshold_b:
                continue
            ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
            if ev_val > settings.ev_cap:
                continue
            recos.append({**base,
                "niche":       niche,
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

    # ── Tie-break dans le match (Oui/Non) ─────────────────────────────────
    if event.odds_tiebreak_yes and event.odds_tiebreak_no:
        # P(au moins 1 tie-break) approximation via prob_set : un set
        # se termine 6-6 (donc TB) avec probabilité ≈ p_set × q_set × C(12,6)/2
        # On utilise une approche plus simple : 1 - P(aucun set 6-6 sur ~2.5 sets)
        from math import comb
        p_set = prob_set(hold_a, hold_b)
        q_set = 1 - p_set
        # P(set serré → 6-6) — approximation empirique sur l'écart de force
        p_66 = min(0.18, 4 * p_set * q_set * 0.13)  # ~13% en moyenne ATP, plus faible si match déséquilibré
        e_sets = 2.5  # BO3 moyen
        p_no_tb = (1 - p_66) ** e_sets
        p_tb = round(1 - p_no_tb, 4)

        for p_est, odds_betclic, desc, niche in [
            (p_tb,        event.odds_tiebreak_yes, "Tie-break dans le match : Oui", "tiebreak_yes"),
            (1.0 - p_tb,  event.odds_tiebreak_no,  "Tie-break dans le match : Non", "tiebreak_no"),
        ]:
            if p_est <= 0.01:
                continue
            odds_fair = round(1 / p_est, 3)
            val = compute_value(odds_betclic, odds_fair)
            if val <= settings.ev_threshold_b:
                continue
            ev_val, rf, rf_lbl, stake = _stake(p_est, odds_betclic, balance_b)
            if ev_val > settings.ev_cap:
                continue
            recos.append({**base,
                "niche":       niche,
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
    import re as _re
    now = datetime.now(timezone.utc)
    scrape_cutoff = (now - timedelta(hours=24)).isoformat()
    horizon_end_dt = now + timedelta(hours=horizon_hours)

    def _parse_event_dt(raw: str | None) -> datetime | None:
        """Best-effort : ISO complet, "YYYY-MM-DD" ou juste "HH:MM" (Betclic
        renvoie souvent que l'heure → on assume aujourd'hui ou demain selon
        si l'heure est passée ou pas)."""
        if not raw:
            return None
        try:
            if "T" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if _re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
                return datetime.fromisoformat(raw + "T00:00:00+00:00")
            m = _re.match(r"^(\d{1,2}):(\d{2})$", raw)
            if m:
                hh, mm = int(m.group(1)), int(m.group(2))
                today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                # Si l'heure est passée d'au moins 30 min, c'est demain
                return today if today >= now - timedelta(minutes=30) else today + timedelta(days=1)
        except Exception:
            return None
        return None

    # Événements scrapés récemment, dédupliqués par event_id (on garde le
    # snapshot LE PLUS RÉCENT par match — sinon un même match scrapé 3 fois
    # produit 3 recos identiques) ET dont event_date est dans la fenêtre.
    events_q = db.query(OddsHistory).filter(OddsHistory.scraped_at >= scrape_cutoff)
    by_eid: dict[str, OddsHistory] = {}
    for e in events_q.all():
        prev = by_eid.get(e.event_id)
        if prev is None or (e.scraped_at or "") > (prev.scraped_at or ""):
            by_eid[e.event_id] = e

    events = []
    for e in by_eid.values():
        if not e.event_date:
            events.append(e); continue
        ed = _parse_event_dt(e.event_date)
        if ed is None:
            events.append(e); continue  # safety : on garde si parse foireux
        if now - timedelta(minutes=30) <= ed <= horizon_end_dt:
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

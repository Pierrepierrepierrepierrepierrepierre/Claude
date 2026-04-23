import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from pydantic import BaseModel
from typing import Optional
from backend.db.database import engine, Base, SessionLocal
from backend.db.crud import get_all_portfolios, get_last_scraper_status, get_bets
from backend.db.models import ScraperLog, Recommendation
from config import settings

PROD = os.getenv("BETTINGEDGE_PROD", "0") == "1"

# Auto-scrape Betclic au démarrage de l'app si le dernier scrape est trop vieux.
# Désactivable via env BETTINGEDGE_NO_AUTOSCRAPE=1.
AUTOSCRAPE_ON_STARTUP = os.getenv("BETTINGEDGE_NO_AUTOSCRAPE", "0") != "1"
AUTOSCRAPE_MAX_AGE_MIN = int(os.getenv("BETTINGEDGE_AUTOSCRAPE_AGE_MIN", "60"))


def _maybe_autoscrape_betclic():
    """Lance un scrape Betclic en thread séparé si le dernier date de > N min.
    Évite de re-scraper si l'app redémarre plusieurs fois en peu de temps."""
    from datetime import datetime, timezone, timedelta
    from backend.db.models import ScraperLog
    db = SessionLocal()
    try:
        last = db.query(ScraperLog).filter_by(scraper="betclic", status="ok") \
                 .order_by(ScraperLog.ran_at.desc()).first()
        if last:
            try:
                last_dt = datetime.fromisoformat(last.ran_at.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if age_min < AUTOSCRAPE_MAX_AGE_MIN:
                    print(f"[autoscrape] dernier scrape Betclic OK il y a {age_min:.0f} min — skip")
                    return
            except Exception:
                pass
    finally:
        db.close()

    print(f"[autoscrape] lancement Betclic au démarrage (background, fenêtre headed)...")
    import threading
    from backend.scrapers.betclic import run as run_betclic
    threading.Thread(target=run_betclic, kwargs={"headless": False}, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = None
    if PROD:
        from scheduler import make_scheduler
        scheduler = make_scheduler()
        scheduler.start()
    if AUTOSCRAPE_ON_STARTUP:
        _maybe_autoscrape_betclic()
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(title="BettingEdge", lifespan=lifespan)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "db": db_status}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
def dashboard(period_days: int = 0):
    db: Session = SessionLocal()
    try:
        portfolios = get_all_portfolios(db)
        port_data = {}

        from datetime import datetime, timedelta
        cutoff = None
        if period_days > 0:
            cutoff = (datetime.utcnow() - timedelta(days=period_days)).isoformat()

        for p in portfolios:
            bets_all = get_bets(db, strategy=p.strategy, resolved=True)
            bets = [b for b in bets_all if not cutoff or (b.resolved_at and b.resolved_at >= cutoff)]

            clv_values = [
                (b.odds_taken / b.odds_close - 1)
                for b in bets if b.odds_close and b.odds_close > 0
            ]
            clv_mean = sum(clv_values) / len(clv_values) if clv_values else 0.0

            # ROI = profit total / mise totale
            total_stake = sum(b.stake for b in bets if b.stake)
            total_profit = sum(
                b.stake * (b.odds_taken - 1) if b.result == 1 else -b.stake
                for b in bets if b.result is not None and b.stake
            )
            roi = total_profit / total_stake if total_stake > 0 else 0.0

            # % paris EV+
            n_ev_pos = sum(1 for b in bets if b.ev_expected and b.ev_expected > 0)
            pct_ev_pos = n_ev_pos / len(bets) * 100 if bets else 0.0

            # Drawdown max
            drawdown_max = 0.0
            peak = p.capital_initial
            for b in sorted(bets, key=lambda x: x.resolved_at or ""):
                val = b.portfolio_after or peak
                if val > peak:
                    peak = val
                dd = (peak - val) / peak if peak > 0 else 0.0
                drawdown_max = max(drawdown_max, dd)

            port_data[p.strategy] = {
                "capital_initial": p.capital_initial,
                "capital_current": p.capital_current,
                "balance": p.balance,
                "n_bets": len(bets),
                "roi": round(roi, 4),
                "roi_pct": round(roi * 100, 2),
                "clv_mean": round(clv_mean, 4),
                "clv_mean_pct": round(clv_mean * 100, 2),
                "pct_ev_pos": round(pct_ev_pos, 1),
                "drawdown_max": round(drawdown_max, 4),
                "drawdown_max_pct": round(drawdown_max * 100, 2),
                "brier_score": 0.25,  # recalculé par Epic 7
            }

        # Série temporelle
        series = []
        for strategy in ["A", "B", "C"]:
            bets = get_bets(db, strategy=strategy, resolved=True)
            if cutoff:
                bets = [b for b in bets if b.resolved_at and b.resolved_at >= cutoff]
            points = [
                {"x": b.resolved_at[:10], "y": round(b.portfolio_after, 2)}
                for b in reversed(bets)
                if b.portfolio_after and b.resolved_at
            ]
            # Ajouter point de départ
            port = next((p for p in portfolios if p.strategy == strategy), None)
            if port and points:
                points = [{"x": points[0]["x"], "y": round(port.capital_initial, 2)}] + points
            series.append({"strategy": strategy, "points": points})

        # Statut scrapers — on prend le dernier OK (sinon dernier tout court)
        # pour ne pas afficher d'erreur quand on a un succès plus récent
        scraper_statuses = {}
        for scraper in ["betclic", "fbref", "tennis_abstract"]:
            last_any = db.query(ScraperLog).filter_by(scraper=scraper) \
                         .order_by(ScraperLog.ran_at.desc()).first()
            last_ok  = db.query(ScraperLog).filter_by(scraper=scraper, status="ok") \
                         .order_by(ScraperLog.ran_at.desc()).first()
            # Si on a un OK plus récent (ou égal) que la dernière entrée en erreur, on
            # affiche le OK pour ne pas polluer l'UI
            chosen = last_any
            if last_ok and (not last_any or last_ok.ran_at >= last_any.ran_at or last_any.status == "error"):
                # Erreur plus récente seulement si > 1h après le dernier OK
                if last_any and last_any.status == "error" and last_ok:
                    if last_any.ran_at > last_ok.ran_at:
                        # Erreur après le OK : on affiche l'erreur uniquement si elle date de < 6h
                        from datetime import datetime, timezone, timedelta
                        try:
                            err_dt = datetime.fromisoformat(last_any.ran_at.replace("Z", "+00:00"))
                            if (datetime.now(timezone.utc) - err_dt) > timedelta(hours=6):
                                chosen = last_ok
                        except Exception:
                            pass
                else:
                    chosen = last_ok
            scraper_statuses[scraper] = {
                "status": chosen.status if chosen else "jamais",
                "ran_at": chosen.ran_at if chosen else None,
                "message": chosen.message if chosen else None,
            }

        scraper_error = next(
            (f"{k}: {v['status']}" for k, v in scraper_statuses.items() if v["status"] not in ("ok", "jamais")),
            None
        )

        return {
            "status": "ok",
            "portfolios": port_data,
            "series": series,
            "scraper_statuses": scraper_statuses,
            "scraper_error": scraper_error,
        }
    finally:
        db.close()


# ── Scraper ───────────────────────────────────────────────────────────────────

@app.get("/api/scraper/status")
def scraper_status():
    db: Session = SessionLocal()
    try:
        result = {}
        for scraper in ["betclic", "fbref", "tennis_abstract"]:
            log = db.query(ScraperLog).filter_by(scraper=scraper).order_by(ScraperLog.ran_at.desc()).first()
            result[scraper] = {"status": log.status, "ran_at": log.ran_at, "message": log.message} if log else None
        return {"status": "ok", "data": result}
    finally:
        db.close()


@app.post("/api/scraper/run")
def scraper_run(scraper: str = "fbref"):
    import threading
    if scraper == "fbref":
        from backend.scrapers.fbref import scrape_all
        threading.Thread(target=scrape_all, daemon=True).start()
    elif scraper == "tennis":
        from backend.scrapers.tennis_abstract import scrape_all
        threading.Thread(target=scrape_all, daemon=True).start()
    elif scraper == "betclic":
        from backend.scrapers.betclic import run
        threading.Thread(target=run, daemon=True).start()
    else:
        raise HTTPException(status_code=400, detail="scraper inconnu")
    return {"status": "ok", "message": f"Scraper {scraper} lancé en arrière-plan"}


# ── Simulation ────────────────────────────────────────────────────────────────

@app.get("/api/simulation/portfolios")
def get_portfolios():
    db: Session = SessionLocal()
    try:
        portfolios = get_all_portfolios(db)
        return {"status": "ok", "data": [
            {"strategy": p.strategy, "capital_initial": p.capital_initial,
             "capital_current": p.capital_current, "n_bets": p.n_bets}
            for p in portfolios
        ]}
    finally:
        db.close()


@app.get("/api/simulation/bets")
def get_simulation_bets(strategy: str = None):
    db: Session = SessionLocal()
    try:
        bets = get_bets(db, strategy=strategy)
        return {"status": "ok", "data": [
            {"id": b.id, "strategy": b.strategy, "market": b.market, "sport": b.sport,
             "odds_taken": b.odds_taken, "stake": b.stake, "ev_expected": b.ev_expected,
             "result": b.result, "ev_realized": b.ev_realized,
             "portfolio_before": b.portfolio_before, "portfolio_after": b.portfolio_after,
             "created_at": b.created_at, "resolved_at": b.resolved_at}
            for b in bets
        ]}
    finally:
        db.close()


@app.post("/api/simulation/record-bet")
def record_bet(data: dict):
    from backend.db.crud import create_bet
    db: Session = SessionLocal()
    try:
        bet = create_bet(db, data)
        return {"status": "ok", "id": bet.id}
    finally:
        db.close()


@app.post("/api/simulation/resolve-bet")
def resolve_bet(bet_id: int, result: int, odds_close: Optional[float] = None):
    """
    Résout un pari. Si `odds_close` est omis, on tente une auto-récupération
    depuis football-data.co.uk (Pinnacle closing) via les métadonnées du pari
    stockées dans features_json (event_name + league + event_date).
    """
    from backend.db.crud import resolve_bet as _resolve
    from backend.db.models import Bet
    import json

    db: Session = SessionLocal()
    try:
        if odds_close is None:
            bet = db.query(Bet).filter_by(id=bet_id).first()
            if bet and bet.features_json:
                try:
                    feats = json.loads(bet.features_json)
                    from backend.core.closing_odds import get_closing_for_event
                    closing = get_closing_for_event(
                        event_name=feats.get("event_name", ""),
                        league_hint=feats.get("league") or bet.league,
                        event_date_iso=feats.get("event_date"),
                    )
                    if closing:
                        # Sélectionne la cote de clôture sur l'issue qui a été pariée
                        outcome = (feats.get("outcome") or "").lower()
                        odds_close = {
                            "home":     closing["pinnacle_home"],
                            "draw":     closing["pinnacle_draw"],
                            "away":     closing["pinnacle_away"],
                            "1":        closing["pinnacle_home"],
                            "x":        closing["pinnacle_draw"],
                            "n":        closing["pinnacle_draw"],
                            "nul":      closing["pinnacle_draw"],
                            "2":        closing["pinnacle_away"],
                        }.get(outcome)
                except Exception:
                    pass
        if odds_close is None:
            raise HTTPException(
                status_code=400,
                detail="odds_close requis (auto-fetch Pinnacle a échoué — vérifier features_json)"
            )
        bet = _resolve(db, bet_id, result, odds_close)
        return {
            "status": "ok",
            "ev_realized": bet.ev_realized,
            "portfolio_after": bet.portfolio_after,
            "odds_close_used": odds_close,
        }
    finally:
        db.close()


# ── Closing odds (Pinnacle via football-data.co.uk) ──────────────────────────

@app.get("/api/closing-odds")
def closing_odds(home: str, away: str, league: Optional[str] = None, event_date: Optional[str] = None):
    """
    Récupère les cotes de clôture Pinnacle (référence sharp) pour un match passé.
    Utile pour calculer le CLV après résolution d'un pari.
    """
    from backend.core.closing_odds import get_pinnacle_closing
    res = get_pinnacle_closing(home, away, league, event_date)
    if not res:
        return {"status": "not_found", "message": "match introuvable ou cotes Pinnacle absentes"}
    return {"status": "ok", "data": res}


# ── Stratégie A — Boosts EV ──────────────────────────────────────────────────

class BoostCalcRequest(BaseModel):
    boost_odds: float
    odds_1x2: Optional[list[float]] = None
    odds_ah: Optional[list[float]] = None
    odds_ou: Optional[list[float]] = None
    weights: Optional[list[float]] = None
    outcome_index: int = 0
    portfolio: str = "A"
    n_similaires: int = 0
    brier_score: float = 0.20
    clv_mean: float = 0.0


@app.post("/api/strategy-a/calculate")
def strategy_a_calculate(req: BoostCalcRequest):
    from backend.strategies.strategy_a import calculate_boost_ev, calculate_stake
    ev_result = calculate_boost_ev(
        boost_odds=req.boost_odds,
        odds_1x2=req.odds_1x2,
        odds_ah=req.odds_ah,
        odds_ou=req.odds_ou,
        weights=req.weights,
        outcome_index=req.outcome_index,
    )
    if "error" in ev_result:
        raise HTTPException(status_code=400, detail=ev_result["error"])

    db: Session = SessionLocal()
    try:
        stake_result = calculate_stake(
            boost_odds=req.boost_odds,
            p_consensus=ev_result["p_consensus"],
            portfolio_name=req.portfolio,
            db=db,
            n_similaires=req.n_similaires,
            brier_score=req.brier_score,
            clv_mean=req.clv_mean,
        )
    finally:
        db.close()

    return {"status": "ok", "ev": ev_result, "stake": stake_result}


@app.get("/api/strategy-a/boosts")
def strategy_a_boosts():
    """
    Retourne les boosts EV+ du pipeline (vrais matchs Betclic).
    Fallback sur le calcul manuel si le pipeline n'a pas encore tourné.
    """
    db: Session = SessionLocal()
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = db.query(Recommendation).filter(
            Recommendation.strategy == "A",
            Recommendation.generated_at >= cutoff,
        ).order_by(Recommendation.value.desc()).all()

        from backend.core.odds_evolution import compute_variation
        data = [{
            "event":        r.event_name,
            "event_id":     r.event_id,
            "sport":        r.sport,
            "boost_odds":   r.odds_betclic,
            "normal_odds":  r.odds_fair,
            "p_consensus":  r.p_estimated,
            "ev":           r.ev,
            "ev_pct":       round(r.ev * 100, 2),
            "stake":        r.stake_recommended,
            "rf":           r.rf,
            "rf_label":     r.rf_label,
            "confidence":   r.confidence,
            "event_date":   r.event_date,
            "variation":    compute_variation(db, r.event_id, r.odds_betclic) if r.event_id else None,
        } for r in rows]

        return {"status": "ok", "data": data, "count": len(data)}
    finally:
        db.close()


# ── Stratégie B — Value Betting niches ───────────────────────────────────────

class NicheCalcRequest(BaseModel):
    niche: str                             # "corners"|"btts"|"cartons"|"aces"|"double_faults"|"tiebreaks"
    sport: str
    odds_betclic: float
    portfolio: str = "B"
    n_similaires: int = 0
    brier_score: float = 0.20
    clv_mean: float = 0.0
    # Foot
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    threshold: Optional[float] = None
    referee: Optional[str] = None
    # Tennis
    player_a: Optional[str] = None
    player_b: Optional[str] = None
    surface: Optional[str] = None
    best_of: int = 3


@app.post("/api/strategy-b/calculate")
def strategy_b_calculate(req: NicheCalcRequest):
    from backend.strategies.strategy_b import NICHE_CALCULATORS
    fn = NICHE_CALCULATORS.get(req.niche)
    if not fn:
        raise HTTPException(status_code=400, detail=f"Niche inconnue : {req.niche}")

    import inspect
    db: Session = SessionLocal()
    try:
        kwargs = req.model_dump(exclude_none=True)
        kwargs.pop("niche", None)
        kwargs.pop("sport", None)
        # Renommer odds_betclic selon la niche
        odds_key = {
            "corners": "odds_over",
            "btts": "odds_btts",
            "cartons": "odds_over",
            "aces": "odds_over",
            "double_faults": "odds_over",
            "tiebreaks": "odds_yes",
        }.get(req.niche, "odds_over")
        kwargs[odds_key] = kwargs.pop("odds_betclic")
        kwargs["db"] = db
        # Filtrer les kwargs non acceptés par la fonction cible
        sig = inspect.signature(fn)
        valid_keys = set(sig.parameters.keys())
        kwargs = {k: v for k, v in kwargs.items() if k in valid_keys}
        result = fn(**kwargs)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"status": "ok", "data": result}
    finally:
        db.close()


@app.get("/api/strategy-b/bets")
def strategy_b_bets(
    sport: Optional[str] = None,
    niche: Optional[str] = None,
    surface: Optional[str] = None,
    ev_min: float = 0.0,
):
    """
    Retourne les value bets actifs générés par le pipeline (vrais matchs).
    Ex : PSG vs Nantes — BTTS value +8.3%, mise 14€.
    """
    db: Session = SessionLocal()
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        q = db.query(Recommendation).filter(
            Recommendation.strategy == "B",
            Recommendation.generated_at >= cutoff,
        )
        if sport:
            q = q.filter(Recommendation.sport == sport)
        if niche:
            q = q.filter(Recommendation.niche == niche)
        if surface:
            q = q.filter(Recommendation.surface == surface)
        if ev_min > 0:
            q = q.filter(Recommendation.ev >= ev_min)

        rows = q.order_by(Recommendation.value.desc()).all()

        from backend.core.odds_evolution import compute_variation
        data = [{
            "event":        r.event_name,
            "event_id":     r.event_id,
            "home_team":    r.home_team,
            "away_team":    r.away_team,
            "player_a":     r.player_a,
            "player_b":     r.player_b,
            "sport":        r.sport,
            "niche":        r.niche,
            "description":  r.description,
            "p_estimated":  r.p_estimated,
            "odds_fair":    r.odds_fair,
            "odds_betclic": r.odds_betclic,
            "value":        r.value,
            "value_pct":    round(r.value * 100, 2),
            "ev":           r.ev,
            "ev_pct":       round(r.ev * 100, 2),
            "rf":           r.rf,
            "rf_label":     r.rf_label,
            "stake":        r.stake_recommended,
            "surface":      r.surface,
            "confidence":   r.confidence,
            "event_date":   r.event_date,
            "variation":    compute_variation(db, r.event_id, r.odds_betclic) if r.event_id else None,
        } for r in rows]

        return {"status": "ok", "data": data, "count": len(data)}
    finally:
        db.close()


# ── Stratégie C — CLV Tracker ────────────────────────────────────────────────

@app.get("/api/strategy-c/clv")
def strategy_c_clv(strategy: str = "C"):
    from backend.strategies.strategy_c import compute_clv_stats
    db: Session = SessionLocal()
    try:
        return {"status": "ok", "data": compute_clv_stats(db, strategy)}
    finally:
        db.close()


@app.get("/api/strategy-c/alerts")
def strategy_c_alerts(threshold: float = 0.05):
    from backend.strategies.strategy_c import detect_line_movements
    db: Session = SessionLocal()
    try:
        movements = detect_line_movements(db, threshold)
        return {"status": "ok", "data": movements, "count": len(movements)}
    finally:
        db.close()


# ── Recommandations (pipeline) ────────────────────────────────────────────────

@app.get("/api/recommendations")
def get_recommendations(
    strategy: Optional[str] = None,
    sport: Optional[str] = None,
    niche: Optional[str] = None,
    min_value: float = 0.0,
    confidence: Optional[str] = None,
):
    """
    Retourne les recommandations générées par le pipeline.
    Ex: PSG vs Nantes → BTTS value +8.3%, mise 14€ portefeuille B.
    """
    db: Session = SessionLocal()
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        q = db.query(Recommendation).filter(Recommendation.generated_at >= cutoff)

        if strategy:
            q = q.filter(Recommendation.strategy == strategy)
        if sport:
            q = q.filter(Recommendation.sport == sport)
        if niche:
            q = q.filter(Recommendation.niche == niche)
        if min_value > 0:
            q = q.filter(Recommendation.value >= min_value)
        if confidence:
            q = q.filter(Recommendation.confidence == confidence)

        rows = q.order_by(Recommendation.value.desc()).all()

        from backend.core.odds_evolution import compute_variation
        data = []
        for r in rows:
            variation = compute_variation(db, r.event_id, r.odds_betclic) if r.event_id else None
            data.append({
                "id":           r.id,
                "event_id":     r.event_id,
                "event_name":   r.event_name,
                "home_team":    r.home_team,
                "away_team":    r.away_team,
                "player_a":     r.player_a,
                "player_b":     r.player_b,
                "event_date":   r.event_date,
                "sport":        r.sport,
                "league":       r.league,
                "surface":      r.surface,
                "strategy":     r.strategy,
                "niche":        r.niche,
                "description":  r.description,
                "p_estimated":  r.p_estimated,
                "odds_fair":    r.odds_fair,
                "odds_betclic": r.odds_betclic,
                "value":        r.value,
                "value_pct":    round(r.value * 100, 2),
                "ev":           r.ev,
                "ev_pct":       round(r.ev * 100, 2),
                "rf":           r.rf,
                "rf_label":     r.rf_label,
                "stake":        r.stake_recommended,
                "confidence":   r.confidence,
                "generated_at": r.generated_at,
                "variation":    variation,  # None si <2 snapshots
            })

        return {"status": "ok", "data": data, "count": len(data)}
    finally:
        db.close()


@app.get("/api/odds-evolution/{event_id}")
def odds_evolution(event_id: str, market_type: str = "1X2"):
    """
    Renvoie la série temporelle complète des cotes pour un événement.
    Utile pour tracer la courbe d'évolution dans le frontend.
    """
    from backend.core.odds_evolution import get_event_snapshots
    db: Session = SessionLocal()
    try:
        snaps = get_event_snapshots(db, event_id, market_type)
        if not snaps:
            return {"status": "not_found", "data": []}
        series = [{
            "scraped_at":    s.scraped_at,
            "odds_home":     s.odds_home,
            "odds_draw":     s.odds_draw,
            "odds_away":     s.odds_away,
            "odds_ou_over":  s.odds_ou_over,
            "odds_ou_under": s.odds_ou_under,
        } for s in snaps]
        return {"status": "ok", "data": series, "count": len(series)}
    finally:
        db.close()


@app.post("/api/pipeline/run")
def run_pipeline_manual():
    """Lance le pipeline d'analyse manuellement (après scraping ou pour rafraîchir)."""
    from backend.pipeline import run_pipeline
    db: Session = SessionLocal()
    try:
        n = run_pipeline(db)
        return {"status": "ok", "recommendations_generated": n}
    finally:
        db.close()


# ── Backtest (Phase D — validation rétrospective sur historique) ────────────

# Cache en mémoire pour éviter de re-télécharger les CSVs à chaque appel
_BACKTEST_CACHE: dict = {}


@app.post("/api/backtest/run")
def backtest_run(
    ev_threshold: float = 0.02,
    flat_stake: float = 10.0,
    leagues: Optional[str] = None,  # CSV ex "ligue1,premier_league"
):
    """
    Rejoue la Stratégie B sur les CSVs football-data (~1700 matchs).
    Cotes Pinnacle closing comme proxy 'Betclic'.
    Retourne les KPIs (ROI, hit rate, breakdown par niche/ligue).

    ⚠️ In-sample (DC calibré sur ces mêmes matchs) → ROI optimiste.
    """
    from backend.learning.backtest import run_backtest
    leagues_list = leagues.split(",") if leagues else None
    try:
        result = run_backtest(
            ev_threshold=ev_threshold,
            flat_stake=flat_stake,
            leagues=leagues_list,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    summary = result.summary()
    # Stocke aussi l'objet BacktestResult complet pour l'export Excel
    _BACKTEST_CACHE["last_result"] = result
    _BACKTEST_CACHE["last"] = {
        "summary": summary,
        "bets": [{
            "league": b.league, "date": b.date,
            "match": f"{b.home} - {b.away}",
            "niche": b.niche,
            "p": round(b.p_estimated * 100, 2),
            "odds": b.odds_taken,
            "ev_pct": round(b.ev_expected * 100, 2),
            "stake": b.stake,
            "won": b.won,
            "profit": b.profit,
        } for b in result.bets],
        "params": {
            "ev_threshold": ev_threshold,
            "flat_stake":  flat_stake,
            "leagues":     leagues_list or list(LEAGUES_KEYS),
        },
    }
    return {"status": "ok", "data": summary}


# Liste des ligues exposée pour le frontend
LEAGUES_KEYS = ["ligue1", "premier_league", "liga", "serie_a", "bundesliga", "ligue2"]


@app.get("/api/backtest/last")
def backtest_last():
    """Renvoie le résultat du dernier backtest (summary + sample des bets)."""
    cached = _BACKTEST_CACHE.get("last")
    if not cached:
        return {"status": "empty", "message": "Aucun backtest lancé pour l'instant"}
    # On ne renvoie que les 100 paris les plus extrêmes (en EV) pour limiter la payload
    bets = sorted(cached["bets"], key=lambda b: -abs(b["ev_pct"]))[:100]
    return {
        "status": "ok",
        "summary": cached["summary"],
        "sample_bets": bets,
        "params": cached["params"],
    }


@app.get("/api/backtest/export.xlsx")
def backtest_export_xlsx():
    """Télécharge le dernier backtest en Excel multi-feuilles."""
    from fastapi.responses import Response
    from backend.learning.backtest import run_backtest
    from backend.learning.backtest_export import export_to_xlsx

    cached = _BACKTEST_CACHE.get("last_result")
    params = (_BACKTEST_CACHE.get("last") or {}).get("params") or {}

    # Si pas de résultat en cache, on relance un backtest avec les params par défaut
    if cached is None:
        cached = run_backtest()
        _BACKTEST_CACHE["last_result"] = cached

    blob = export_to_xlsx(cached, params=params)
    from datetime import datetime
    fname = f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── Static files & pages ──────────────────────────────────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def serve_dashboard():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.get("/{page}")
def serve_page(page: str):
    path = os.path.join(frontend_dir, f"{page}.html")
    if os.path.exists(path):
        return FileResponse(path)
    return FileResponse(os.path.join(frontend_dir, "index.html"))

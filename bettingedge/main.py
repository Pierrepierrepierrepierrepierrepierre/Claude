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
from backend.db.models import ScraperLog
from config import settings

PROD = os.getenv("BETTINGEDGE_PROD", "0") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = None
    if PROD:
        from scheduler import make_scheduler
        scheduler = make_scheduler()
        scheduler.start()
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
def dashboard():
    db: Session = SessionLocal()
    try:
        portfolios = get_all_portfolios(db)
        port_data = {}
        for p in portfolios:
            bets = get_bets(db, strategy=p.strategy, resolved=True)
            clv_values = [
                (b.odds_taken / b.odds_close - 1)
                for b in bets if b.odds_close and b.odds_close > 0
            ]
            clv_mean = sum(clv_values) / len(clv_values) if clv_values else 0.0

            port_data[p.strategy] = {
                "capital_initial": p.capital_initial,
                "capital_current": p.capital_current,
                "n_bets": p.n_bets,
                "clv_mean": round(clv_mean, 4),
                "brier_score": 0.25,  # sera recalculé par Epic 7
            }

        # Série temporelle (capital par pari résolu)
        series = []
        for strategy in ["A", "B", "C"]:
            bets = get_bets(db, strategy=strategy, resolved=True)
            points = [{"x": b.resolved_at[:10], "y": b.portfolio_after} for b in reversed(bets) if b.portfolio_after]
            series.append({"strategy": strategy, "points": points})

        # Statut scraper Betclic
        scraper_error = None
        last = db.query(ScraperLog).filter_by(scraper="betclic").order_by(ScraperLog.ran_at.desc()).first()
        if last and last.status not in ("ok",):
            scraper_error = f"{last.status} — {last.message or ''}"

        return {"status": "ok", "portfolios": port_data, "series": series, "scraper_error": scraper_error}
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
def resolve_bet(bet_id: int, result: int, odds_close: float):
    from backend.db.crud import resolve_bet as _resolve
    db: Session = SessionLocal()
    try:
        bet = _resolve(db, bet_id, result, odds_close)
        return {"status": "ok", "ev_realized": bet.ev_realized, "portfolio_after": bet.portfolio_after}
    finally:
        db.close()


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
    Retourne les boosts EV+ du dernier scraping Betclic.
    Pour l'instant retourne une liste vide si pas de données — le scraper
    doit avoir tourné et marqué des cotes comme is_boost=True.
    """
    from backend.db.models import OddsHistory
    from backend.strategies.strategy_a import get_boost_opportunities
    db: Session = SessionLocal()
    try:
        # Récupère les cotes marquées boost dans les dernières 24h
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        rows = db.query(OddsHistory).filter(OddsHistory.scraped_at >= cutoff).all()
        records = [
            {
                "event_name": r.event_name,
                "market_type": r.market_type,
                "sport": r.sport,
                "odds_home": r.odds_home,
                "odds_draw": r.odds_draw,
                "odds_away": r.odds_away,
                "is_boost": r.is_boost,
                "boost_odds": r.boost_odds,
                "normal_odds": r.normal_odds,
                "outcome_index": r.outcome_index or 0,
                "event_date": r.event_date,
            }
            for r in rows
        ]
        opportunities = get_boost_opportunities(db, records)
        return {"status": "ok", "data": opportunities, "count": len(opportunities)}
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
    Retourne les value bets actifs depuis les données en BDD.
    Pour l'instant retourne une liste vide si pas de données scrapers.
    """
    from backend.strategies.strategy_b import get_value_bets
    db: Session = SessionLocal()
    try:
        # Les candidats viendront du scraper Betclic (marchés secondaires annotés)
        # Pour l'instant, on expose l'endpoint prêt — données remplies par le scraper
        candidates = []
        results = get_value_bets(candidates, db, portfolio="B")

        # Filtres
        if sport:
            results = [r for r in results if r.get("sport") == sport]
        if niche:
            results = [r for r in results if r.get("niche") == niche]
        if surface:
            results = [r for r in results if r.get("surface") == surface]
        if ev_min > 0:
            results = [r for r in results if r.get("ev", 0) >= ev_min]

        return {"status": "ok", "data": results, "count": len(results)}
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

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

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

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

from sqlalchemy.orm import Session
from datetime import datetime, timezone
from .models import Bet, Portfolio, ScraperLog, NichePerformance, ModelParam


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_bet(db: Session, data: dict) -> Bet:
    portfolio = db.query(Portfolio).filter_by(strategy=data["strategy"]).first()
    data["portfolio_before"] = portfolio.capital_current if portfolio else 0.0
    bet = Bet(**data)
    db.add(bet)
    db.commit()
    db.refresh(bet)
    return bet


def resolve_bet(db: Session, bet_id: int, result: int, odds_close: float) -> Bet:
    bet = db.query(Bet).filter_by(id=bet_id).first()
    if not bet:
        raise ValueError(f"Bet {bet_id} not found")

    bet.result = result
    bet.odds_close = odds_close
    bet.resolved_at = _now()

    profit = bet.stake * (bet.odds_taken - 1) if result == 1 else -bet.stake
    bet.ev_realized = profit / bet.stake
    bet.portfolio_after = bet.portfolio_before + profit

    portfolio = db.query(Portfolio).filter_by(strategy=bet.strategy).first()
    if portfolio:
        portfolio.capital_current = bet.portfolio_after
        portfolio.n_bets += 1
        portfolio.updated_at = _now()

    db.commit()
    db.refresh(bet)
    return bet


def get_bets(db: Session, strategy: str = None, resolved: bool = None) -> list[Bet]:
    q = db.query(Bet)
    if strategy:
        q = q.filter_by(strategy=strategy)
    if resolved is True:
        q = q.filter(Bet.result.isnot(None))
    elif resolved is False:
        q = q.filter(Bet.result.is_(None))
    return q.order_by(Bet.created_at.desc()).all()


def get_portfolio(db: Session, strategy: str) -> Portfolio:
    return db.query(Portfolio).filter_by(strategy=strategy).first()


def get_all_portfolios(db: Session) -> list[Portfolio]:
    return db.query(Portfolio).all()


def log_scraper(db: Session, scraper: str, status: str, message: str = None) -> ScraperLog:
    log = ScraperLog(scraper=scraper, status=status, message=message)
    db.add(log)
    db.commit()
    return log


def get_last_scraper_status(db: Session, scraper: str) -> ScraperLog | None:
    return (
        db.query(ScraperLog)
        .filter_by(scraper=scraper)
        .order_by(ScraperLog.ran_at.desc())
        .first()
    )


def upsert_model_param(db: Session, model_name: str, param_name: str, value: float, confidence: float = 1.0):
    param = db.query(ModelParam).filter_by(model_name=model_name, param_name=param_name).first()
    if param:
        param.param_value = value
        param.confidence = confidence
        param.updated_at = _now()
    else:
        param = ModelParam(model_name=model_name, param_name=param_name, param_value=value, confidence=confidence)
        db.add(param)
    db.commit()
    return param


def get_model_params(db: Session, model_name: str) -> dict:
    params = db.query(ModelParam).filter_by(model_name=model_name).all()
    return {p.param_name: p.param_value for p in params}

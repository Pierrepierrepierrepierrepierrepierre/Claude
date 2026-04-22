from sqlalchemy import Column, Integer, Float, Text, UniqueConstraint, Index
from datetime import datetime, timezone
from .database import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Bet(Base):
    __tablename__ = "bets"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    strategy         = Column(Text, nullable=False)
    market           = Column(Text, nullable=False)
    sport            = Column(Text, nullable=False)
    league           = Column(Text)
    surface          = Column(Text)
    p_estimated      = Column(Float, nullable=False)
    odds_taken       = Column(Float, nullable=False)
    odds_close       = Column(Float)
    odds_fair        = Column(Float)
    ev_expected      = Column(Float, nullable=False)
    result           = Column(Integer)
    ev_realized      = Column(Float)
    stake            = Column(Float, nullable=False)
    portfolio_before = Column(Float, nullable=False)
    portfolio_after  = Column(Float)
    features_json    = Column(Text, nullable=False, default="{}")
    created_at       = Column(Text, nullable=False, default=_now)
    resolved_at      = Column(Text)


class ModelParam(Base):
    __tablename__ = "model_params"
    __table_args__ = (UniqueConstraint("model_name", "param_name"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    model_name  = Column(Text, nullable=False)
    param_name  = Column(Text, nullable=False)
    param_value = Column(Float, nullable=False)
    confidence  = Column(Float, default=1.0)
    updated_at  = Column(Text, nullable=False, default=_now)


class OddsHistory(Base):
    __tablename__ = "odds_history"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    event_id    = Column(Text, nullable=False)
    market      = Column(Text, nullable=False)
    bookmaker   = Column(Text, default="betclic")
    odds        = Column(Float, nullable=False)
    recorded_at = Column(Text, nullable=False, default=_now)

    __table_args__ = (
        Index("idx_odds_event", "event_id", "recorded_at"),
    )


class NichePerformance(Base):
    __tablename__ = "niche_performance"

    niche        = Column(Text, primary_key=True)
    n_bets       = Column(Integer, default=0)
    roi          = Column(Float, default=0.0)
    clv_mean     = Column(Float, default=0.0)
    brier_score  = Column(Float, default=0.25)
    last_updated = Column(Text, nullable=False, default=_now)


class Portfolio(Base):
    __tablename__ = "portfolios"

    strategy        = Column(Text, primary_key=True)
    capital_initial = Column(Float, nullable=False)
    capital_current = Column(Float, nullable=False)
    n_bets          = Column(Integer, default=0)
    updated_at      = Column(Text, nullable=False, default=_now)


class ScraperLog(Base):
    __tablename__ = "scraper_logs"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    scraper = Column(Text, nullable=False)
    status  = Column(Text, nullable=False)
    message = Column(Text)
    ran_at  = Column(Text, nullable=False, default=_now)

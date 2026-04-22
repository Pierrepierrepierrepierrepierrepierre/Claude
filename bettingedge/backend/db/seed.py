"""
Initialise la BDD : tables + 3 portefeuilles + niches de base.
Usage : python -m backend.db.seed
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import engine, Base
from backend.db.models import Portfolio, NichePerformance
from sqlalchemy.orm import Session
from config import settings
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


NICHES = [
    "corners_ligue1", "corners_premier_league", "corners_liga",
    "corners_serie_a", "corners_bundesliga",
    "btts_ligue1", "btts_premier_league",
    "cards_ligue1", "cards_premier_league",
    "aces_atp_clay", "aces_atp_hard", "aces_atp_grass",
    "double_faults_atp_clay", "double_faults_atp_hard",
    "tiebreaks_atp",
]


def seed():
    Base.metadata.create_all(bind=engine)
    print("Tables créées.")

    with Session(engine) as db:
        for strategy in ["A", "B", "C"]:
            existing = db.query(Portfolio).filter_by(strategy=strategy).first()
            if not existing:
                db.add(Portfolio(
                    strategy=strategy,
                    capital_initial=settings.capital_initial,
                    capital_current=settings.capital_initial,
                    updated_at=_now(),
                ))
        db.commit()
        print(f"Portefeuilles A/B/C initialisés à {settings.capital_initial}€.")

        for niche in NICHES:
            existing = db.query(NichePerformance).filter_by(niche=niche).first()
            if not existing:
                db.add(NichePerformance(niche=niche, last_updated=_now()))
        db.commit()
        print(f"{len(NICHES)} niches initialisées.")

    print("Seed terminé. BDD prête.")


if __name__ == "__main__":
    seed()

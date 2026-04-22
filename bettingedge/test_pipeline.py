"""
Test du pipeline : injecte des matchs fictifs réalistes et vérifie les recommandations.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone
from backend.db.database import SessionLocal
from backend.db.models import OddsHistory, ModelParam, Recommendation
from backend.pipeline import run_pipeline

def _now():
    return datetime.now(timezone.utc).isoformat()

def seed_params(db):
    """Injecte les paramètres Dixon-Coles et tennis minimaux pour le test."""
    dc_params = [
        # PSG vs Nantes
        ("att_paris_saint_germain", 1.80),
        ("def_paris_saint_germain", 0.65),
        ("att_nantes",              0.90),
        ("def_nantes",              1.10),
        # Barcelona vs Atletico
        ("att_barcelona",           1.70),
        ("def_barcelona",           0.70),
        ("att_atletico_madrid",     1.20),
        ("def_atletico_madrid",     0.75),
        # Paramètres globaux
        ("gamma",  1.20),
        ("rho",   -0.13),
    ]
    tennis_params = [
        # Djokovic vs Alcaraz
        ("ace_rate_djokovic_hard",   0.072),
        ("ace_rate_alcaraz_hard",    0.065),
        ("ace_rate_avg_hard",        0.08),
    ]

    for name, val in dc_params:
        existing = db.query(ModelParam).filter_by(model_name="dixon_coles", param_name=name).first()
        if existing:
            existing.param_value = val
        else:
            db.add(ModelParam(model_name="dixon_coles", param_name=name, param_value=val))

    for name, val in tennis_params:
        existing = db.query(ModelParam).filter_by(model_name="tennis", param_name=name).first()
        if existing:
            existing.param_value = val
        else:
            db.add(ModelParam(model_name="tennis", param_name=name, param_value=val))

    db.commit()
    print("Paramètres DC + tennis injectés.")


def seed_events(db):
    """Injecte des événements OddsHistory fictifs avec des cotes légèrement erronées (value+ détectable)."""
    events = [
        # PSG vs Nantes — 1X2 + Over2.5
        OddsHistory(
            event_id    ="test_psg_nantes_001",
            event_name  ="Paris Saint-Germain - Nantes",
            event_date  ="2026-04-22T21:00:00",
            sport       ="football",
            league      ="Ligue 1",
            market_type ="1X2",
            bookmaker   ="betclic",
            odds_home   =1.55,   # PSG favori (la cote est un peu généreuse)
            odds_draw   =4.10,
            odds_away   =6.50,
            odds_ou_over=1.75,   # Over 2.5 buts
            odds_ou_under=2.10,
            scraped_at  =_now(),
        ),
        # Barcelona vs Atletico Madrid — 1X2
        OddsHistory(
            event_id    ="test_barca_atletico_001",
            event_name  ="FC Barcelone - Atletico Madrid",
            event_date  ="2026-04-22T21:00:00",
            sport       ="football",
            league      ="La Liga",
            market_type ="1X2",
            bookmaker   ="betclic",
            odds_home   =1.80,
            odds_draw   =3.80,
            odds_away   =4.50,
            odds_ou_over=1.90,
            odds_ou_under=1.95,
            scraped_at  =_now(),
        ),
        # Djokovic vs Alcaraz — Tennis 1X2
        OddsHistory(
            event_id    ="test_djokovic_alcaraz_001",
            event_name  ="Novak Djokovic - Carlos Alcaraz",
            event_date  ="2026-04-22T15:00:00",
            sport       ="tennis",
            league      ="ATP Masters Hard",
            market_type ="1X2",
            bookmaker   ="betclic",
            odds_home   =2.10,   # Djokovic légèrement outsider
            odds_away   =1.72,   # Alcaraz favori
            scraped_at  =_now(),
        ),
    ]

    for ev in events:
        existing = db.query(OddsHistory).filter_by(event_id=ev.event_id).first()
        if existing:
            db.delete(existing)
    db.commit()
    for ev in events:
        db.add(ev)
    db.commit()
    print(f"{len(events)} événements de test injectés.")


def run_and_display(db):
    """Lance le pipeline et affiche les recommandations générées."""
    n = run_pipeline(db)
    print(f"\n=== {n} recommandations générées ===\n")

    recos = db.query(Recommendation).all()
    if not recos:
        print("Aucune recommandation trouvée.")
        return

    for r in recos:
        print(f"[{r.strategy}] {r.event_name}")
        print(f"  Niche      : {r.niche}")
        print(f"  Description: {r.description}")
        print(f"  P estimée  : {r.p_estimated:.1%}")
        print(f"  Cote juste : {r.odds_fair}")
        print(f"  Cote Betclic: {r.odds_betclic}")
        print(f"  Value      : {r.value:+.1%}")
        print(f"  EV         : {r.ev:+.1%}")
        print(f"  RF         : {r.rf:.2f} ({r.rf_label})")
        print(f"  Mise reco  : {r.stake_recommended:.2f}€")
        print(f"  Confidence : {r.confidence}")
        print()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        print("1. Injection des paramètres de modèle...")
        seed_params(db)
        print("2. Injection des événements Betclic fictifs...")
        seed_events(db)
        print("3. Lancement du pipeline d'analyse...\n")
        run_and_display(db)
    finally:
        db.close()

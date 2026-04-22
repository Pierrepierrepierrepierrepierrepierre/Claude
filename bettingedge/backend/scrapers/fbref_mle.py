"""
Recalibration Dixon-Coles MLE complète, par ligue.

Le scraper rapide `fbref.py` fait une simple normalisation buts/moyenne, ce
qui sur-estime les nuls. Ce script lance la version MLE (`models.dixon_coles.fit`)
qui calibre proprement att_i, def_i, gamma, rho via maximum de vraisemblance.

Coût : ~1-2 min par ligue, 6 ligues → 6-12 min total. À lancer ponctuellement
(une fois par semaine par exemple), pas à chaque scraping.

Usage : python -m backend.scrapers.fbref_mle
"""
import io
import time
import sys
import os
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import upsert_model_param, log_scraper
from backend.models.dixon_coles import fit


LEAGUES = {
    "ligue1":         "F1",
    "premier_league": "E0",
    "liga":           "SP1",
    "serie_a":        "I1",
    "bundesliga":     "D1",
    "ligue2":         "F2",
}
SEASON = "2526"
BASE_URL = "https://www.football-data.co.uk/mmz4281"


def fetch_fixtures(code: str) -> list[dict]:
    url = f"{BASE_URL}/{SEASON}/{code}.csv"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text)).dropna(subset=["FTHG", "FTAG"])
    return [
        {
            "home": row.HomeTeam,
            "away": row.AwayTeam,
            "home_goals": int(row.FTHG),
            "away_goals": int(row.FTAG),
        }
        for row in df.itertuples()
    ]


def recalibrate_all() -> bool:
    db = SessionLocal()
    try:
        # On collecte gamma/rho des ligues les plus fournies pour pondérer
        gammas, rhos = [], []
        n_teams_total = 0

        for league, code in LEAGUES.items():
            print(f"\n[{league}] téléchargement...")
            fixtures = fetch_fixtures(code)
            print(f"  {len(fixtures)} matchs — fit MLE en cours...")
            t0 = time.time()
            params = fit(fixtures)
            dt = time.time() - t0
            print(f"  fit terminé en {dt:.0f}s — gamma={params['gamma']} rho={params['rho']}")

            saved = 0
            for k, v in params.items():
                if k.startswith(("att_", "def_")):
                    upsert_model_param(db, "dixon_coles", k, v)
                    saved += 1
            print(f"  {saved // 2} équipes calibrées et sauvegardées")
            n_teams_total += saved // 2

            gammas.append(params["gamma"])
            rhos.append(params["rho"])

        # Moyennes pondérées (toutes ligues équivalentes en taille)
        gamma_avg = round(sum(gammas) / len(gammas), 4) if gammas else 1.20
        rho_avg = round(sum(rhos) / len(rhos), 4) if rhos else -0.13
        upsert_model_param(db, "dixon_coles", "gamma", gamma_avg)
        upsert_model_param(db, "dixon_coles", "rho", rho_avg)

        msg = f"MLE recalibré : {n_teams_total} équipes, gamma={gamma_avg}, rho={rho_avg}"
        log_scraper(db, "fbref_mle", "ok", msg)
        print(f"\n✓ {msg}")
        return True

    except Exception as e:
        log_scraper(db, "fbref_mle", "error", str(e))
        print(f"ERREUR : {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    recalibrate_all()

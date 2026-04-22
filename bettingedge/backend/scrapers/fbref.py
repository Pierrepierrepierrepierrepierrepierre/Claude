"""
Scraper FBref — stats foot pour Dixon-Coles.
Usage : python -m backend.scrapers.fbref [--bootstrap]
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import upsert_model_param, log_scraper, get_model_params
from datetime import datetime, timezone

LEAGUES = {
    "ligue1":          "https://fbref.com/en/comps/13/schedule/Ligue-1-Scores-and-Fixtures",
    "premier_league":  "https://fbref.com/en/comps/9/schedule/Premier-League-Scores-and-Fixtures",
    "liga":            "https://fbref.com/en/comps/12/schedule/La-Liga-Scores-and-Fixtures",
    "serie_a":         "https://fbref.com/en/comps/11/schedule/Serie-A-Scores-and-Fixtures",
    "bundesliga":      "https://fbref.com/en/comps/20/schedule/Bundesliga-Scores-and-Fixtures",
    "ligue2":          "https://fbref.com/en/comps/60/schedule/Ligue-2-Scores-and-Fixtures",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://fbref.com/",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sleep():
    time.sleep(random.uniform(4, 9))


def fetch_fixtures(league: str, url: str) -> list[dict]:
    """Récupère les résultats de la saison courante pour une ligue."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERREUR] {league}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": lambda x: x and "sched" in x})
    if not table:
        print(f"  [WARN] {league}: table non trouvée")
        return []

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 8:
            continue
        try:
            score_td = tr.find("td", {"data-stat": "score"})
            home_td  = tr.find("td", {"data-stat": "home_team"})
            away_td  = tr.find("td", {"data-stat": "away_team"})
            if not (score_td and home_td and away_td):
                continue
            score_text = score_td.get_text(strip=True)
            if "–" not in score_text and "-" not in score_text:
                continue
            sep = "–" if "–" in score_text else "-"
            home_goals, away_goals = score_text.split(sep)
            rows.append({
                "home": home_td.get_text(strip=True),
                "away": away_td.get_text(strip=True),
                "home_goals": int(home_goals.strip()),
                "away_goals": int(away_goals.strip()),
                "league": league,
            })
        except Exception:
            continue

    print(f"  {league}: {len(rows)} matchs récupérés")
    return rows


def compute_attack_defense(fixtures: list[dict]) -> dict:
    """
    Calcule att_i et def_i par équipe (méthode simplifiée Dixon-Coles).
    att_i = moyenne buts marqués / moyenne globale
    def_i = moyenne buts concédés / moyenne globale
    """
    if not fixtures:
        return {}

    df = pd.DataFrame(fixtures)
    avg_goals = (df["home_goals"].sum() + df["away_goals"].sum()) / (2 * len(df))
    if avg_goals == 0:
        return {}

    teams = set(df["home"].tolist()) | set(df["away"].tolist())
    params = {}

    for team in teams:
        home_m = df[df["home"] == team]
        away_m = df[df["away"] == team]

        scored   = home_m["home_goals"].sum() + away_m["away_goals"].sum()
        conceded = home_m["away_goals"].sum() + away_m["home_goals"].sum()
        n_games  = len(home_m) + len(away_m)

        if n_games < 3:
            continue

        att = (scored / n_games) / avg_goals
        defe = (conceded / n_games) / avg_goals
        params[team] = {"att": round(att, 4), "def": round(defe, 4), "n": n_games}

    return params


def scrape_all(bootstrap: bool = False) -> bool:
    """Scrape toutes les ligues et sauvegarde les paramètres en BDD."""
    db = SessionLocal()
    all_fixtures = []

    try:
        for league, url in LEAGUES.items():
            print(f"Scraping {league}...")
            fixtures = fetch_fixtures(league, url)
            all_fixtures.extend(fixtures)
            _sleep()

        if not all_fixtures:
            log_scraper(db, "fbref", "error", "Aucun match récupéré")
            return False

        params = compute_attack_defense(all_fixtures)
        saved = 0

        for team, p in params.items():
            team_key = team.lower().replace(" ", "_").replace("-", "_")
            upsert_model_param(db, "dixon_coles", f"att_{team_key}", p["att"])
            upsert_model_param(db, "dixon_coles", f"def_{team_key}", p["def"])
            saved += 1

        # Paramètres globaux Dixon-Coles
        upsert_model_param(db, "dixon_coles", "gamma", 1.20)   # avantage domicile
        upsert_model_param(db, "dixon_coles", "rho",   -0.13)  # correction scores bas

        log_scraper(db, "fbref", "ok", f"{saved} équipes calibrées sur {len(all_fixtures)} matchs")
        print(f"\nFBref OK — {saved} équipes, {len(all_fixtures)} matchs")

        if bootstrap:
            print("Bootstrap Dixon-Coles terminé. Prêt pour les premiers paris.")

        return True

    except Exception as e:
        log_scraper(db, "fbref", "error", str(e))
        print(f"ERREUR: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap = "--bootstrap" in sys.argv
    scrape_all(bootstrap=bootstrap)

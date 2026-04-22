"""
Calibration Dixon-Coles + corners + cartons depuis football-data.co.uk.

Note : ce module s'appelait à l'origine `fbref` et scrapait FBref.com, mais
FBref bloque désormais les requêtes (Cloudflare 403). On a basculé sur
football-data.co.uk — CSVs gratuits, pas d'API key, mêmes données saison
courante + colonnes corners (HC/AC), cartons (HY/AY/HR/AR), et cotes Pinnacle
closing (PSCH/PSCD/PSCA) utiles pour le CLV.

Le nom du module reste `fbref` pour ne pas casser les imports existants.

Usage : python -m backend.scrapers.fbref [--bootstrap]
"""
import requests
import io
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import upsert_model_param, log_scraper

# Codes ligue football-data.co.uk pour la saison courante (2025/2026 = "2526")
LEAGUES = {
    "ligue1":         "F1",
    "premier_league": "E0",
    "liga":           "SP1",
    "serie_a":        "I1",
    "bundesliga":     "D1",
    "ligue2":         "F2",
}

SEASON = "2526"  # 2025/2026
BASE_URL = "https://www.football-data.co.uk/mmz4281"


def fetch_league(league: str, code: str) -> pd.DataFrame:
    """Télécharge le CSV d'une ligue pour la saison courante."""
    url = f"{BASE_URL}/{SEASON}/{code}.csv"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # Colonnes obligatoires
        required = {"HomeTeam", "AwayTeam", "FTHG", "FTAG"}
        if not required.issubset(df.columns):
            print(f"  [WARN] {league}: colonnes manquantes")
            return pd.DataFrame()
        # Filtre les matchs joués (FTHG non-NA)
        df = df.dropna(subset=["FTHG", "FTAG"]).copy()
        df["league"] = league
        print(f"  {league}: {len(df)} matchs récupérés")
        return df
    except Exception as e:
        print(f"  [ERREUR] {league}: {e}")
        return pd.DataFrame()


def _team_key(name: str) -> str:
    """Normalise un nom d'équipe en clé BDD (lowercase, underscores)."""
    return str(name).lower().strip().replace(" ", "_").replace("-", "_").replace(".", "")


def compute_dixon_coles(df: pd.DataFrame) -> dict:
    """
    Calcule att_i et def_i par équipe (Dixon-Coles simplifié).
    att_i = (buts marqués / matchs) / moyenne globale
    def_i = (buts concédés / matchs) / moyenne globale
    """
    if df.empty:
        return {}
    avg_goals = (df["FTHG"].sum() + df["FTAG"].sum()) / (2 * len(df))
    if avg_goals == 0:
        return {}

    teams = set(df["HomeTeam"]) | set(df["AwayTeam"])
    params = {}
    for team in teams:
        home_m = df[df["HomeTeam"] == team]
        away_m = df[df["AwayTeam"] == team]
        n = len(home_m) + len(away_m)
        if n < 3:
            continue
        scored = home_m["FTHG"].sum() + away_m["FTAG"].sum()
        conceded = home_m["FTAG"].sum() + away_m["FTHG"].sum()
        params[team] = {
            "att": round((scored / n) / avg_goals, 4),
            "def": round((conceded / n) / avg_goals, 4),
            "n": n,
        }
    return params


def compute_secondary_stats(df: pd.DataFrame) -> dict:
    """
    Moyennes corners et cartons par équipe — utilisées par Stratégie B.
    Retourne {team: {corners_for, corners_against, cards_for, cards_against, n}}
    """
    if df.empty:
        return {}
    has_corners = {"HC", "AC"}.issubset(df.columns)
    has_cards = {"HY", "AY"}.issubset(df.columns)
    if not (has_corners or has_cards):
        return {}

    teams = set(df["HomeTeam"]) | set(df["AwayTeam"])
    out = {}
    for team in teams:
        home_m = df[df["HomeTeam"] == team]
        away_m = df[df["AwayTeam"] == team]
        n = len(home_m) + len(away_m)
        if n < 3:
            continue
        d = {"n": n}
        if has_corners:
            d["corners_for"] = round(
                (home_m["HC"].sum() + away_m["AC"].sum()) / n, 3
            )
            d["corners_against"] = round(
                (home_m["AC"].sum() + away_m["HC"].sum()) / n, 3
            )
        if has_cards:
            # Cartons jaunes seulement (HY/AY) — les rouges sont rares et bruyants
            d["cards_for"] = round(
                (home_m["HY"].sum() + away_m["AY"].sum()) / n, 3
            )
            d["cards_against"] = round(
                (home_m["AY"].sum() + away_m["HY"].sum()) / n, 3
            )
        out[team] = d
    return out


def scrape_all(bootstrap: bool = False) -> bool:
    """Télécharge toutes les ligues et calibre Dixon-Coles + stats secondaires."""
    db = SessionLocal()
    all_df = []

    try:
        for league, code in LEAGUES.items():
            print(f"Téléchargement {league}...")
            df = fetch_league(league, code)
            if not df.empty:
                all_df.append(df)

        if not all_df:
            log_scraper(db, "fbref", "error", "Aucune ligue téléchargée")
            return False

        full = pd.concat(all_df, ignore_index=True)

        dc_params = compute_dixon_coles(full)
        sec_params = compute_secondary_stats(full)

        saved_dc = 0
        for team, p in dc_params.items():
            key = _team_key(team)
            upsert_model_param(db, "dixon_coles", f"att_{key}", p["att"])
            upsert_model_param(db, "dixon_coles", f"def_{key}", p["def"])
            saved_dc += 1

        saved_sec = 0
        for team, p in sec_params.items():
            key = _team_key(team)
            for stat, val in p.items():
                if stat == "n":
                    continue
                upsert_model_param(db, "secondary", f"{stat}_{key}", val)
            saved_sec += 1

        # Paramètres globaux Dixon-Coles
        upsert_model_param(db, "dixon_coles", "gamma", 1.20)
        upsert_model_param(db, "dixon_coles", "rho",   -0.13)

        msg = f"{saved_dc} équipes calibrées DC, {saved_sec} avec stats secondaires, sur {len(full)} matchs"
        log_scraper(db, "fbref", "ok", msg)
        print(f"\nOK — {msg}")

        if bootstrap:
            print("Bootstrap Dixon-Coles terminé. Prêt pour les premiers paris.")

        return True

    except Exception as e:
        log_scraper(db, "fbref", "error", str(e))
        print(f"ERREUR: {e}")
        import traceback; traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap = "--bootstrap" in sys.argv
    scrape_all(bootstrap=bootstrap)

"""
Scraper Tennis Abstract — ace rates et double fautes par joueur/surface.
Usage : python -m backend.scrapers.tennis_abstract
"""
import requests
from bs4 import BeautifulSoup
import time
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import upsert_model_param, log_scraper

SURFACES = ["hard", "clay", "grass"]

# URLs par surface — stats serveur ATP
URLS = {
    "hard":  "https://www.tennisabstract.com/reports/atp_hard_serve.html",
    "clay":  "https://www.tennisabstract.com/reports/atp_clay_serve.html",
    "grass": "https://www.tennisabstract.com/reports/atp_grass_serve.html",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.tennisabstract.com/",
}

MIN_MATCHES = 5  # ignorer les joueurs avec trop peu de données


def _sleep():
    time.sleep(random.uniform(3, 7))


def fetch_serve_stats(surface: str) -> list[dict]:
    url = URLS[surface]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERREUR] {surface}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"  [WARN] {surface}: table non trouvée")
        return []

    rows = []
    headers_row = [th.get_text(strip=True).lower() for th in table.find("tr").find_all(["th", "td"])]

    def col(name: str) -> int:
        for i, h in enumerate(headers_row):
            if name in h:
                return i
        return -1

    idx_player = col("player")
    idx_matches = col("match")
    idx_aces = col("ace")
    idx_df = col("df")
    idx_svpt = col("svpt")

    if idx_player < 0:
        return []

    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        try:
            player  = cells[idx_player].get_text(strip=True) if idx_player >= 0 else ""
            matches = int(cells[idx_matches].get_text(strip=True)) if idx_matches >= 0 else 0
            if not player or matches < MIN_MATCHES:
                continue

            ace_pct = float(cells[idx_aces].get_text(strip=True).replace("%", "")) / 100 if idx_aces >= 0 else 0.06
            df_pct  = float(cells[idx_df].get_text(strip=True).replace("%", "")) / 100 if idx_df >= 0 else 0.03

            rows.append({"player": player, "surface": surface, "ace_rate": ace_pct, "df_rate": df_pct, "matches": matches})
        except Exception:
            continue

    print(f"  {surface}: {len(rows)} joueurs")
    return rows


def scrape_all() -> bool:
    db = SessionLocal()
    total = 0

    try:
        for surface in SURFACES:
            print(f"Tennis Abstract — {surface}...")
            stats = fetch_serve_stats(surface)

            for s in stats:
                key = s["player"].lower().replace(" ", "_").replace(".", "").replace("-", "_")
                upsert_model_param(db, "poisson_aces", f"ace_rate_{key}_{surface}", s["ace_rate"])
                upsert_model_param(db, "poisson_df",   f"df_rate_{key}_{surface}",  s["df_rate"])
                total += 1

            _sleep()

        log_scraper(db, "tennis_abstract", "ok", f"{total} paramètres joueur/surface")
        print(f"\nTennis Abstract OK — {total} paramètres sauvegardés")
        return True

    except Exception as e:
        log_scraper(db, "tennis_abstract", "error", str(e))
        print(f"ERREUR: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    scrape_all()

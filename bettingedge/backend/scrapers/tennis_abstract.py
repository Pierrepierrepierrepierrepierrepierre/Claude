"""
Calibration ace_rate / df_rate par joueur ATP/WTA et par surface.

Source : datasets de Jeff Sackmann (github.com/JeffSackmann/tennis_atp et
tennis_wta) — open source, format CSV par saison, alimente Tennis Abstract
en backend. Plus stable que le scraping HTML qui change tout le temps.

Le module garde le nom historique `tennis_abstract` pour ne pas casser
les imports (main.py / scheduler.py).

Usage : python -m backend.scrapers.tennis_abstract
"""
import io
import sys
import os
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import upsert_model_param, log_scraper

# Saisons à charger (les + récentes pour rester représentatif)
SEASONS = [2024, 2023]

# URLs base
ATP_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
WTA_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

# Mapping surface CSV → clé BDD
SURFACE_MAP = {"Hard": "hard", "Clay": "clay", "Grass": "grass", "Carpet": "hard"}

MIN_SVPT = 100  # nombre minimum de points de service pour calculer un taux fiable


def _player_key(name: str) -> str:
    return str(name).lower().strip().replace(" ", "_").replace(".", "").replace("-", "_").replace("'", "")


def _fetch_season(base: str, year: int, prefix: str) -> pd.DataFrame:
    """Charge un CSV de saison."""
    url = f"{base}/{prefix}_matches_{year}.csv"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), low_memory=False)
        print(f"  {prefix} {year}: {len(df)} matchs")
        return df
    except Exception as e:
        print(f"  [WARN] {prefix} {year}: {e}")
        return pd.DataFrame()


def _aggregate_player_surface(df: pd.DataFrame) -> dict:
    """
    Pour chaque joueur (winner+loser confondus), agrège par surface :
      ace_rate = sum(aces) / sum(svpt)
      df_rate  = sum(df)   / sum(svpt)
    Retourne {player_key: {surface: {ace_rate, df_rate, svpt}}}
    """
    if df.empty or "surface" not in df.columns:
        return {}

    cols_needed = {"winner_name", "loser_name", "surface", "w_ace", "w_df", "w_svpt", "l_ace", "l_df", "l_svpt"}
    if not cols_needed.issubset(df.columns):
        return {}

    df = df.dropna(subset=["surface", "w_svpt", "l_svpt"]).copy()
    df["surface_key"] = df["surface"].map(SURFACE_MAP)
    df = df.dropna(subset=["surface_key"])

    # Long format : une ligne par (joueur, match)
    winners = df.rename(columns={
        "winner_name": "player", "w_ace": "ace", "w_df": "df", "w_svpt": "svpt",
    })[["player", "surface_key", "ace", "df", "svpt"]]
    losers = df.rename(columns={
        "loser_name": "player",  "l_ace": "ace", "l_df": "df", "l_svpt": "svpt",
    })[["player", "surface_key", "ace", "df", "svpt"]]
    long = pd.concat([winners, losers], ignore_index=True).dropna(subset=["ace", "df", "svpt"])

    grouped = long.groupby(["player", "surface_key"]).agg(
        ace=("ace", "sum"), df=("df", "sum"), svpt=("svpt", "sum")
    ).reset_index()
    grouped = grouped[grouped["svpt"] >= MIN_SVPT]

    out: dict = {}
    for row in grouped.itertuples():
        key = _player_key(row.player)
        out.setdefault(key, {})[row.surface_key] = {
            "ace_rate": round(row.ace / row.svpt, 4),
            "df_rate":  round(row.df  / row.svpt, 4),
            "svpt":     int(row.svpt),
        }
    return out


def scrape_all() -> bool:
    db = SessionLocal()
    total_atp = total_wta = 0

    try:
        # ── ATP ──────────────────────────────────────────────────────────
        atp_dfs = [_fetch_season(ATP_BASE, y, "atp") for y in SEASONS]
        atp_full = pd.concat([d for d in atp_dfs if not d.empty], ignore_index=True)
        atp_stats = _aggregate_player_surface(atp_full)
        avg_ace = {"hard": [], "clay": [], "grass": []}
        avg_df  = {"hard": [], "clay": [], "grass": []}

        for player, surfs in atp_stats.items():
            for surface, st in surfs.items():
                upsert_model_param(db, "tennis", f"ace_rate_{player}_{surface}", st["ace_rate"])
                upsert_model_param(db, "tennis", f"df_rate_{player}_{surface}",  st["df_rate"])
                avg_ace[surface].append(st["ace_rate"])
                avg_df[surface].append(st["df_rate"])
                total_atp += 1

        # ── WTA ──────────────────────────────────────────────────────────
        wta_dfs = [_fetch_season(WTA_BASE, y, "wta") for y in SEASONS]
        wta_full = pd.concat([d for d in wta_dfs if not d.empty], ignore_index=True)
        wta_stats = _aggregate_player_surface(wta_full)
        for player, surfs in wta_stats.items():
            for surface, st in surfs.items():
                upsert_model_param(db, "tennis", f"ace_rate_{player}_{surface}", st["ace_rate"])
                upsert_model_param(db, "tennis", f"df_rate_{player}_{surface}",  st["df_rate"])
                avg_ace[surface].append(st["ace_rate"])
                avg_df[surface].append(st["df_rate"])
                total_wta += 1

        # ── Moyennes par surface (fallback joueurs inconnus) ────────────
        for surface in ("hard", "clay", "grass"):
            if avg_ace[surface]:
                upsert_model_param(db, "tennis", f"ace_rate_avg_{surface}",
                                   round(sum(avg_ace[surface]) / len(avg_ace[surface]), 4))
            if avg_df[surface]:
                upsert_model_param(db, "tennis", f"df_rate_avg_{surface}",
                                   round(sum(avg_df[surface])  / len(avg_df[surface]),  4))

        msg = f"{total_atp} ATP + {total_wta} WTA = {total_atp + total_wta} (joueur,surface) calibrés"
        log_scraper(db, "tennis_abstract", "ok", msg)
        print(f"\nOK -- {msg}")
        return True

    except Exception as e:
        log_scraper(db, "tennis_abstract", "error", str(e))
        print(f"ERREUR : {e}")
        import traceback; traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    scrape_all()

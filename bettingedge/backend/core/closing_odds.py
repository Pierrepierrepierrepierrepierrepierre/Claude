"""
Récupère les cotes de clôture Pinnacle depuis football-data.co.uk.

Pinnacle = bookmaker de référence pour le sharp consensus → utilisé comme
pivot CLV. CLV = cote_taken / cote_pinnacle_closing - 1.

Les CSVs football-data sont mis à jour ~quotidiennement et contiennent les
colonnes PSCH/PSCD/PSCA (Pinnacle Closing Home/Draw/Away). On télécharge
les fichiers à la volée et on cache en mémoire pour la session courante.

Le mapping nom Betclic → nom football-data passe par TEAM_MAP, donc on
réutilise resolve_team du module team_mapping.
"""
import io
import time
import requests
import pandas as pd
from datetime import datetime
from difflib import get_close_matches

from backend.core.team_mapping import resolve_team, parse_event_name


# Codes football-data.co.uk pour la saison courante
LEAGUE_CODES = {
    "ligue1":         "F1",
    "ligue 1":        "F1",
    "premier_league": "E0",
    "premier league": "E0",
    "epl":            "E0",
    "liga":           "SP1",
    "la liga":        "SP1",
    "serie_a":        "I1",
    "serie a":        "I1",
    "bundesliga":     "D1",
    "ligue2":         "F2",
    "ligue 2":        "F2",
}

SEASON = "2526"  # 2025/2026
BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Cache mémoire — TTL 1h (les CSVs ne bougent pas plus vite que ça)
_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_TTL_SECONDS = 3600


def _normalize_league(league: str | None) -> str | None:
    """Mappe un nom de ligue arbitraire vers un code football-data."""
    if not league:
        return None
    key = league.lower().strip()
    if key in LEAGUE_CODES:
        return LEAGUE_CODES[key]
    # Match partiel
    for alias, code in LEAGUE_CODES.items():
        if alias in key or key in alias:
            return code
    return None


def _fetch_league_df(code: str) -> pd.DataFrame | None:
    """Télécharge (ou récupère du cache) le DataFrame d'une ligue."""
    now = time.time()
    cached = _CACHE.get(code)
    if cached and (now - cached[0]) < _TTL_SECONDS:
        return cached[1]

    url = f"{BASE_URL}/{SEASON}/{code}.csv"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        _CACHE[code] = (now, df)
        return df
    except Exception as e:
        print(f"[closing_odds] erreur fetch {code}: {e}")
        return None


def _fuzzy_team(name: str, candidates: list[str]) -> str | None:
    """Match flou d'un nom contre la liste des HomeTeam/AwayTeam de football-data."""
    if not name:
        return None
    matches = get_close_matches(name.lower(), [c.lower() for c in candidates], n=1, cutoff=0.7)
    if not matches:
        return None
    matched_lower = matches[0]
    for c in candidates:
        if c.lower() == matched_lower:
            return c
    return None


def get_pinnacle_closing(
    home_betclic: str,
    away_betclic: str,
    league_hint: str | None = None,
    event_date_iso: str | None = None,
) -> dict | None:
    """
    Récupère les cotes Pinnacle de clôture pour un match.

    Stratégie :
      1. Si league_hint connu → cherche dans la bonne ligue
      2. Sinon → balaye toutes les ligues
      3. Match par TEAM_MAP puis fuzzy sur HomeTeam/AwayTeam
      4. Retourne {pinnacle_home, pinnacle_draw, pinnacle_away, league, match_date}

    Renvoie None si introuvable.
    """
    # Normaliser via TEAM_MAP — donne les clés football-data normalisées
    home_key, _ = resolve_team(home_betclic)
    away_key, _ = resolve_team(away_betclic)

    code = _normalize_league(league_hint)
    leagues_to_try = [code] if code else list(set(LEAGUE_CODES.values()))

    for c in leagues_to_try:
        if not c:
            continue
        df = _fetch_league_df(c)
        if df is None or df.empty:
            continue

        # Normaliser les noms du CSV pour matcher la clé TEAM_MAP
        df = df.copy()
        df["_home_key"] = df["HomeTeam"].apply(
            lambda x: str(x).lower().strip().replace(" ", "_").replace("-", "_").replace(".", "")
        )
        df["_away_key"] = df["AwayTeam"].apply(
            lambda x: str(x).lower().strip().replace(" ", "_").replace("-", "_").replace(".", "")
        )

        # Match exact via clés
        match = df[(df["_home_key"] == home_key) & (df["_away_key"] == away_key)]

        # Sinon match fuzzy
        if match.empty:
            home_alt = _fuzzy_team(home_key, df["_home_key"].tolist())
            away_alt = _fuzzy_team(away_key, df["_away_key"].tolist())
            if home_alt and away_alt:
                match = df[(df["_home_key"] == home_alt) & (df["_away_key"] == away_alt)]

        if match.empty:
            continue

        # Si plusieurs (matchs aller/retour), prend celui le plus proche de event_date
        if len(match) > 1 and event_date_iso:
            try:
                target = datetime.fromisoformat(event_date_iso[:10])
                match["_dist"] = match["Date"].apply(
                    lambda d: abs((datetime.strptime(d, "%d/%m/%Y") - target).days)
                )
                match = match.nsmallest(1, "_dist")
            except Exception:
                match = match.tail(1)
        else:
            match = match.tail(1)

        row = match.iloc[0]
        # Pinnacle closing — peut être absent sur les matchs très récents
        psch = row.get("PSCH")
        pscd = row.get("PSCD")
        psca = row.get("PSCA")
        if pd.isna(psch) or pd.isna(pscd) or pd.isna(psca):
            # Fallback Bet365 si Pinnacle manquant
            psch = row.get("B365H") if pd.isna(psch) else psch
            pscd = row.get("B365D") if pd.isna(pscd) else pscd
            psca = row.get("B365A") if pd.isna(psca) else psca

        if pd.isna(psch) or pd.isna(pscd) or pd.isna(psca):
            return None

        return {
            "pinnacle_home": float(psch),
            "pinnacle_draw": float(pscd),
            "pinnacle_away": float(psca),
            "league_code":   c,
            "match_date":    str(row["Date"]),
            "score":         f"{int(row['FTHG'])}-{int(row['FTAG'])}" if "FTHG" in row else None,
            "home_csv":      str(row["HomeTeam"]),
            "away_csv":      str(row["AwayTeam"]),
        }

    return None


def get_closing_for_event(
    event_name: str,
    league_hint: str | None = None,
    event_date_iso: str | None = None,
) -> dict | None:
    """Variante pratique : prend un event_name (ex: 'Paris SG - Nantes')
    et déduit home/away via parse_event_name."""
    home, away = parse_event_name(event_name)
    if not home or not away:
        return None
    return get_pinnacle_closing(home, away, league_hint, event_date_iso)


def compute_clv(odds_taken: float, closing_odds: float) -> float:
    """CLV = cote_taken / cote_closing - 1.
    Positif = on a pris une cote plus haute que la clôture sharp → bon signe."""
    if not closing_odds or closing_odds <= 0:
        return 0.0
    return odds_taken / closing_odds - 1

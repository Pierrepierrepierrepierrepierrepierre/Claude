"""
Moteur de backtest — rejoue les stratégies sur l'historique football-data.

Pour chaque match déjà joué cette saison :
  1. On utilise les cotes Pinnacle de clôture comme proxy "cote Betclic"
     (Pinnacle = sharp consensus, c'est ce qu'on tente de battre)
  2. On calcule p_estimée via Dixon-Coles (params actuels en BDD)
  3. Si EV = p × cote - 1 > seuil → on enregistre un pari simulé
  4. Le résultat est connu (FTHG/FTAG du CSV) → gain ou perte
  5. On agrège ROI, % gains, breakdown par niche, Brier

⚠️ Limitation : le modèle DC actuel est calibré SUR ces matchs (in-sample).
Le ROI est donc optimiste — du look-ahead bias. Une vraie validation
demanderait du walk-forward (re-calibrer mois par mois) — TODO.

Marchés simulés :
  - 1X2 (3 outcomes)
  - BTTS Yes/No (depuis colonnes B365 BTTS Y/N quand dispo, sinon skip)
  - Over/Under 2.5 (P>2.5/P<2.5)
"""
import io
import sys
import os
import requests
import pandas as pd
from dataclasses import dataclass, field
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import get_model_params
from backend.models.dixon_coles import (
    predict_from_params, prob_home_win, prob_draw, prob_away_win,
    prob_btts, prob_over,
)
from config import settings


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


def _team_key(name: str) -> str:
    return str(name).lower().strip().replace(" ", "_").replace("-", "_").replace(".", "")


def _ev(p: float, odds: float) -> float:
    return p * odds - 1


@dataclass
class BacktestBet:
    league: str
    date: str
    home: str
    away: str
    niche: str          # "1x2_home", "1x2_draw", "1x2_away", "btts_yes", "btts_no", "over25", "under25"
    p_estimated: float
    odds_taken: float
    odds_fair: float
    ev_expected: float
    stake: float        # mise en flat ou Kelly fractionné
    won: bool           # True/False selon score réel
    profit: float       # +stake×(odds-1) si won, -stake sinon


@dataclass
class BacktestResult:
    n_bets: int = 0
    n_won: int = 0
    total_stake: float = 0.0
    total_profit: float = 0.0
    by_niche: dict = field(default_factory=lambda: defaultdict(lambda: {
        "n": 0, "won": 0, "stake": 0.0, "profit": 0.0
    }))
    by_league: dict = field(default_factory=lambda: defaultdict(lambda: {
        "n": 0, "won": 0, "stake": 0.0, "profit": 0.0
    }))
    bets: list = field(default_factory=list)

    @property
    def roi(self) -> float:
        return self.total_profit / self.total_stake if self.total_stake > 0 else 0.0

    @property
    def hit_rate(self) -> float:
        return self.n_won / self.n_bets if self.n_bets > 0 else 0.0

    def add(self, bet: BacktestBet):
        self.bets.append(bet)
        self.n_bets += 1
        self.total_stake += bet.stake
        self.total_profit += bet.profit
        if bet.won:
            self.n_won += 1
        for d, key in [(self.by_niche, bet.niche), (self.by_league, bet.league)]:
            d[key]["n"] += 1
            d[key]["stake"] += bet.stake
            d[key]["profit"] += bet.profit
            if bet.won:
                d[key]["won"] += 1

    def summary(self) -> dict:
        return {
            "n_bets":        self.n_bets,
            "n_won":         self.n_won,
            "hit_rate":      round(self.hit_rate, 4),
            "hit_rate_pct":  round(self.hit_rate * 100, 2),
            "total_stake":   round(self.total_stake, 2),
            "total_profit":  round(self.total_profit, 2),
            "roi":           round(self.roi, 4),
            "roi_pct":       round(self.roi * 100, 2),
            "by_niche": {k: {**v,
                "roi": round(v["profit"] / v["stake"], 4) if v["stake"] > 0 else 0.0,
                "hit_rate": round(v["won"] / v["n"], 4) if v["n"] > 0 else 0.0,
            } for k, v in self.by_niche.items()},
            "by_league": {k: {**v,
                "roi": round(v["profit"] / v["stake"], 4) if v["stake"] > 0 else 0.0,
            } for k, v in self.by_league.items()},
        }


def _fetch_league(code: str) -> pd.DataFrame:
    url = f"{BASE_URL}/{SEASON}/{code}.csv"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text)).dropna(subset=["FTHG", "FTAG"])
    # Renomme les colonnes O/U avec '>' et '<' (inaccessibles via itertuples)
    rename_map = {
        "B365>2.5": "B365_over25", "B365<2.5": "B365_under25",
        "P>2.5":    "P_over25",    "P<2.5":    "P_under25",
        "Avg>2.5":  "Avg_over25",  "Avg<2.5":  "Avg_under25",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    return df


def _stake_flat(odds: float, base: float = 10.0) -> float:
    """Mise flat (10€ par défaut) — backtest simple pour comparer ROI sans
    confondre avec sizing. On pourra ajouter Kelly plus tard."""
    return base


def run_backtest(
    ev_threshold: float = None,
    flat_stake: float = 10.0,
    leagues: list[str] = None,
) -> BacktestResult:
    """
    Lance le backtest de Stratégie B sur les CSVs football-data.

    ev_threshold : minimum EV pour parier (défaut = settings.ev_threshold_b)
    flat_stake   : mise constante (€) pour comparer ROI sans biais de sizing
    leagues      : liste des ligues (clés LEAGUES). None = toutes.
    """
    if ev_threshold is None:
        ev_threshold = settings.ev_threshold_b
    target_leagues = leagues or list(LEAGUES.keys())

    db = SessionLocal()
    try:
        dc_params = get_model_params(db, "dixon_coles")
    finally:
        db.close()

    if not dc_params:
        raise RuntimeError("Aucun param Dixon-Coles en BDD — lance d'abord fbref_mle")

    gamma = dc_params.get("gamma", 1.20)
    rho   = dc_params.get("rho", -0.13)
    result = BacktestResult()

    for league in target_leagues:
        code = LEAGUES.get(league)
        if not code:
            continue
        try:
            df = _fetch_league(code)
        except Exception as e:
            print(f"[WARN] {league}: {e}")
            continue

        for row in df.itertuples():
            home = _team_key(row.HomeTeam)
            away = _team_key(row.AwayTeam)
            if f"att_{home}" not in dc_params or f"att_{away}" not in dc_params:
                continue
            try:
                matrix = predict_from_params(home, away, dc_params, gamma, rho)
            except Exception:
                continue

            p_h = prob_home_win(matrix)
            p_d = prob_draw(matrix)
            p_a = prob_away_win(matrix)
            p_btts = prob_btts(matrix)
            p_over = prob_over(matrix, 2.5)

            hg, ag = int(row.FTHG), int(row.FTAG)
            home_won = hg > ag
            away_won = hg < ag
            draw     = hg == ag
            btts     = hg >= 1 and ag >= 1
            over25   = (hg + ag) > 2.5

            # Cotes de référence (Pinnacle closing > Bet365 fallback)
            def _odds(field_pin: str, field_b365: str) -> float | None:
                v = getattr(row, field_pin, None)
                if v is None or pd.isna(v):
                    v = getattr(row, field_b365, None)
                if v is None or pd.isna(v):
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            o_h = _odds("PSCH", "B365H")
            o_d = _odds("PSCD", "B365D")
            o_a = _odds("PSCA", "B365A")
            # O/U : Pinnacle (P_over25/P_under25) ou fallback Bet365 / moyenne
            o_over  = _odds("P_over25",  "B365_over25")
            o_under = _odds("P_under25", "B365_under25")
            if o_over is None:
                o_over = getattr(row, "Avg_over25", None)
                if o_over is not None and pd.isna(o_over): o_over = None
            if o_under is None:
                o_under = getattr(row, "Avg_under25", None)
                if o_under is not None and pd.isna(o_under): o_under = None

            candidates = []
            # 1X2
            if o_h: candidates.append(("1x2_home", p_h, o_h, home_won))
            if o_d: candidates.append(("1x2_draw", p_d, o_d, draw))
            if o_a: candidates.append(("1x2_away", p_a, o_a, away_won))
            # O/U 2.5 (si dispo) — même nommage que le pipeline live
            if o_over and o_under:
                candidates.append(("over_2.5",  p_over,       o_over,  over25))
                candidates.append(("under_2.5", 1.0 - p_over, o_under, not over25))

            for niche, p_est, odds, won in candidates:
                if p_est <= 0 or odds <= 1:
                    continue
                # Mêmes filtres que le pipeline live (cohérence backtest ↔ prod)
                if any(niche.startswith(p) for p in (settings.disabled_niches or [])):
                    continue
                if f"{niche}:{league}" in (settings.blacklist_combos or []):
                    continue
                ev = _ev(p_est, odds)
                if ev <= ev_threshold:
                    continue
                if ev > settings.ev_cap:
                    continue
                # Mitigation Nul (cf pipeline)
                if niche == "1x2_draw" and ev <= ev_threshold + settings.ev_threshold_draw_extra:
                    continue
                stake = _stake_flat(odds, flat_stake)
                profit = stake * (odds - 1) if won else -stake
                result.add(BacktestBet(
                    league=league,
                    date=str(row.Date) if hasattr(row, "Date") else "",
                    home=row.HomeTeam,
                    away=row.AwayTeam,
                    niche=niche,
                    p_estimated=round(p_est, 4),
                    odds_taken=round(odds, 3),
                    odds_fair=round(1 / p_est, 3),
                    ev_expected=round(ev, 4),
                    stake=stake,
                    won=won,
                    profit=round(profit, 2),
                ))

    return result


if __name__ == "__main__":
    r = run_backtest()
    s = r.summary()
    print(f"\n=== Backtest Strategy B (in-sample) ===")
    print(f"Paris simulés  : {s['n_bets']}")
    print(f"Hit rate       : {s['hit_rate_pct']}%")
    print(f"Mise totale    : {s['total_stake']:.2f} €")
    print(f"Profit total   : {s['total_profit']:+.2f} €")
    print(f"ROI            : {s['roi_pct']:+.2f}%")
    print(f"\nPar niche :")
    for niche, st in sorted(s["by_niche"].items(), key=lambda x: -x[1].get("roi", 0)):
        print(f"  {niche:12s}: n={st['n']:4d}  hit={st['hit_rate']*100:5.1f}%  ROI={st['roi']*100:+6.2f}%  profit={st['profit']:+8.2f}")
    print(f"\nPar ligue :")
    for league, st in s["by_league"].items():
        print(f"  {league:18s}: n={st['n']:4d}  ROI={st['roi']*100:+6.2f}%  profit={st['profit']:+8.2f}")

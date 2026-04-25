"""
Walk-forward backtest — validation OUT-OF-SAMPLE.

Le backtest standard (`backtest.py`) est in-sample : le modèle Dixon-Coles
est calibré sur ces mêmes matchs → le ROI est optimiste (look-ahead bias).

Walk-forward simule ce qu'aurait vraiment vécu un parieur live :
  - Pour chaque mois M de la saison :
      - Calibrer DC MLE sur uniquement les matchs antérieurs au mois M
      - Tester sur les matchs du mois M (out-of-sample, OOS)
      - Stocker les paris + résultats
  - Agrégation finale : ROI mensuel + cumulé OOS

Coût : ~8 mois × 30s/calibration = ~4 min.
Mois trop précoces (< 50 matchs entraînement) sont skippés.

Comparaison OOS vs IS = mesure de l'overfitting du modèle.
"""
import io
import sys
import os
import time
import requests
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.models.dixon_coles import (
    fit, predict_from_params, prob_home_win, prob_draw, prob_away_win,
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

# Min matchs PAR LIGUE pour calibrer (chaque ligue a ~18-20 équipes,
# faut ~3-4 matchs / équipe minimum pour que MLE converge proprement)
MIN_TRAINING_MATCHES_PER_LEAGUE = 60


@dataclass
class WFMonthResult:
    month: str         # "2025-09"
    n_train: int
    n_test_matches: int
    n_bets: int
    n_won: int
    stake: float
    profit: float
    fit_seconds: float
    by_niche: dict = field(default_factory=lambda: defaultdict(lambda: {"n": 0, "won": 0, "stake": 0.0, "profit": 0.0}))

    @property
    def roi(self) -> float:
        return self.profit / self.stake if self.stake > 0 else 0.0


def _team_key(name: str) -> str:
    return str(name).lower().strip().replace(" ", "_").replace("-", "_").replace(".", "")


def _fetch_all_leagues() -> pd.DataFrame:
    """Charge tous les CSVs et concatène avec colonne league."""
    parts = []
    for league, code in LEAGUES.items():
        url = f"{BASE_URL}/{SEASON}/{code}.csv"
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text)).dropna(subset=["FTHG", "FTAG"])
            df["league"] = league
            df["date_dt"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
            df = df.dropna(subset=["date_dt"])
            # Renomme cols O/U avec '<' '>' (inaccessibles via itertuples)
            df = df.rename(columns={
                "B365>2.5": "B365_over25", "B365<2.5": "B365_under25",
                "P>2.5":    "P_over25",    "P<2.5":    "P_under25",
                "Avg>2.5":  "Avg_over25",  "Avg<2.5":  "Avg_under25",
            })
            parts.append(df)
        except Exception as e:
            print(f"  [WARN] {league}: {e}")
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).sort_values("date_dt").reset_index(drop=True)


def _odds_from_row(row, prim: str, fallback: str) -> float | None:
    v = getattr(row, prim, None)
    if v is None or pd.isna(v):
        v = getattr(row, fallback, None)
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _generate_bets_for_month(test_df: pd.DataFrame, params: dict, flat_stake: float,
                              ev_threshold_override: float | None = None) -> list[dict]:
    """Pour chaque match du mois, génère les paris EV+ et calcule le résultat."""
    if not params:
        return []
    gamma = params.get("gamma", 1.20)
    rho   = params.get("rho", -0.13)
    ev_min = ev_threshold_override if ev_threshold_override is not None else settings.ev_threshold_b
    bets = []
    for row in test_df.itertuples():
        home = _team_key(row.HomeTeam)
        away = _team_key(row.AwayTeam)
        if f"att_{home}" not in params or f"att_{away}" not in params:
            continue
        try:
            matrix = predict_from_params(home, away, params, gamma, rho)
        except Exception:
            continue
        p_h = prob_home_win(matrix)
        p_d = prob_draw(matrix)
        p_a = prob_away_win(matrix)
        p_over = prob_over(matrix, 2.5)

        hg, ag = int(row.FTHG), int(row.FTAG)
        home_won = hg > ag
        away_won = hg < ag
        draw     = hg == ag
        over25   = (hg + ag) > 2.5

        o_h = _odds_from_row(row, "PSCH", "B365H")
        o_d = _odds_from_row(row, "PSCD", "B365D")
        o_a = _odds_from_row(row, "PSCA", "B365A")
        o_over  = _odds_from_row(row, "P_over25",  "B365_over25")
        o_under = _odds_from_row(row, "P_under25", "B365_under25")

        candidates = []
        if o_h: candidates.append(("1x2_home", p_h, o_h, home_won))
        if o_d: candidates.append(("1x2_draw", p_d, o_d, draw))
        if o_a: candidates.append(("1x2_away", p_a, o_a, away_won))
        if o_over and o_under:
            candidates.append(("over_2.5",  p_over,       o_over,  over25))
            candidates.append(("under_2.5", 1.0 - p_over, o_under, not over25))

        for niche, p, odds, won in candidates:
            if p <= 0 or odds <= 1: continue
            # Mêmes filtres que la prod
            if any(niche.startswith(p2) for p2 in (settings.disabled_niches or [])):
                continue
            if f"{niche}:{row.league}" in (settings.blacklist_combos or []):
                continue
            ev = p * odds - 1
            if ev <= ev_min: continue
            if ev > settings.ev_cap: continue
            if niche == "1x2_draw" and ev <= ev_min + settings.ev_threshold_draw_extra:
                continue
            profit = flat_stake * (odds - 1) if won else -flat_stake
            bets.append({
                "league": row.league, "date": str(row.Date), "home": row.HomeTeam, "away": row.AwayTeam,
                "niche": niche, "p": round(p, 4), "odds": round(odds, 3),
                "ev_pct": round(ev * 100, 2), "stake": flat_stake, "won": won,
                "profit": round(profit, 2),
            })
    return bets


def run_walkforward(
    flat_stake: float = 10.0,
    min_training_per_league: int = MIN_TRAINING_MATCHES_PER_LEAGUE,
    target_months: list[str] | None = None,
    leagues_filter: list[str] | None = None,
    ev_threshold: float | None = None,
) -> dict:
    """
    Walk-forward : pour chaque mois CIBLE, pour chaque ligue, calibrer DC
    UNIQUEMENT sur les matchs antérieurs au mois cible.

    - target_months : liste ex ["2025-10", "2025-11"]. None = tous les mois.
    - leagues_filter : liste ex ["ligue1", "premier_league"]. None = toutes.
    - ev_threshold : seuil EV custom. None = config par défaut.

    Renvoie {months: [...], totals: {...}, by_niche: {...}, all_bets: [...]}
    """
    full = _fetch_all_leagues()
    if full.empty:
        return {"error": "Aucune donnée chargée depuis football-data.co.uk"}

    full["month"] = full["date_dt"].dt.strftime("%Y-%m")
    all_months = sorted(full["month"].unique())
    months_to_test = target_months if target_months else all_months
    months_to_test = [m for m in months_to_test if m in all_months]
    if not months_to_test:
        return {"error": "Aucun mois valide à tester"}

    leagues_set = sorted(full["league"].unique())
    if leagues_filter:
        leagues_set = [l for l in leagues_set if l in leagues_filter]

    print(f"Walk-forward : test sur {len(months_to_test)} mois "
          f"({months_to_test[0]} -> {months_to_test[-1]}), "
          f"{len(leagues_set)} ligue(s), calibration par ligue", flush=True)

    all_bets = []
    monthly: list[WFMonthResult] = []

    for month in months_to_test:
        test_df  = full[(full["month"] == month) & (full["league"].isin(leagues_set))]

        # Calibre par ligue (18-20 équipes par MLE → rapide et stable)
        params_by_league: dict[str, dict] = {}
        total_train = 0
        total_fit_s = 0.0
        skipped_leagues: list[str] = []
        for league in leagues_set:
            train_l = full[(full["month"] < month) & (full["league"] == league)]
            if len(train_l) < min_training_per_league:
                skipped_leagues.append(league)
                continue
            t0 = time.time()
            fixtures = [
                {"home": r.HomeTeam, "away": r.AwayTeam, "home_goals": int(r.FTHG), "away_goals": int(r.FTAG)}
                for r in train_l.itertuples()
            ]
            try:
                params_by_league[league] = fit(fixtures)
            except Exception as e:
                print(f"    [warn] fit {league}/{month} err: {e}", flush=True)
                continue
            total_fit_s += time.time() - t0
            total_train += len(train_l)

        if not params_by_league:
            print(f"  {month}: skip (toutes ligues sous le seuil train={min_training_per_league})", flush=True)
            continue

        # Génère les paris OOS du mois en utilisant les params de la ligue du match
        bets: list[dict] = []
        for league, lparams in params_by_league.items():
            test_l = test_df[test_df["league"] == league]
            if test_l.empty:
                continue
            bets.extend(_generate_bets_for_month(test_l, lparams, flat_stake, ev_threshold))
        print(f"  {month}: train_total={total_train} test={len(test_df)} fit_total={total_fit_s:.0f}s "
              f"calibre={len(params_by_league)}/{len(leagues_set)} ligues n_bets={len(bets)}", flush=True)
        all_bets.extend([{**b, "month": month} for b in bets])
        dt = total_fit_s

        won = sum(1 for b in bets if b["won"])
        stake = sum(b["stake"] for b in bets)
        profit = sum(b["profit"] for b in bets)
        m_res = WFMonthResult(
            month=month, n_train=total_train, n_test_matches=len(test_df),
            n_bets=len(bets), n_won=won, stake=stake, profit=profit, fit_seconds=round(dt, 1),
        )
        # Breakdown niche
        for b in bets:
            n = m_res.by_niche[b["niche"]]
            n["n"] += 1; n["stake"] += b["stake"]; n["profit"] += b["profit"]
            if b["won"]: n["won"] += 1
        monthly.append(m_res)

    # Agrégation
    cum_profit = 0.0
    months_summary = []
    for m in monthly:
        cum_profit += m.profit
        months_summary.append({
            "month": m.month,
            "n_train": m.n_train,
            "n_test_matches": m.n_test_matches,
            "n_bets": m.n_bets,
            "hit_rate_pct": round((m.n_won / m.n_bets * 100) if m.n_bets else 0, 1),
            "stake": round(m.stake, 2),
            "profit": round(m.profit, 2),
            "roi_pct": round(m.roi * 100, 2),
            "cumulative_profit": round(cum_profit, 2),
            "fit_seconds": m.fit_seconds,
            "by_niche": {k: {**v,
                "roi_pct": round(v["profit"] / v["stake"] * 100, 2) if v["stake"] > 0 else 0.0,
            } for k, v in m.by_niche.items()},
        })

    total_stake = sum(m.stake for m in monthly)
    total_profit = sum(m.profit for m in monthly)
    total_bets = sum(m.n_bets for m in monthly)
    total_won  = sum(m.n_won for m in monthly)

    # Breakdown niche cumulé OOS
    niche_agg = defaultdict(lambda: {"n": 0, "won": 0, "stake": 0.0, "profit": 0.0})
    for m in monthly:
        for k, v in m.by_niche.items():
            niche_agg[k]["n"] += v["n"]
            niche_agg[k]["won"] += v["won"]
            niche_agg[k]["stake"] += v["stake"]
            niche_agg[k]["profit"] += v["profit"]

    return {
        "months": months_summary,
        "totals": {
            "n_months_tested": len(monthly),
            "n_bets": total_bets,
            "n_won": total_won,
            "hit_rate_pct": round((total_won / total_bets * 100) if total_bets else 0, 2),
            "total_stake": round(total_stake, 2),
            "total_profit": round(total_profit, 2),
            "roi_pct": round((total_profit / total_stake * 100) if total_stake > 0 else 0, 2),
        },
        "by_niche": {k: {**v,
            "roi_pct": round(v["profit"] / v["stake"] * 100, 2) if v["stake"] > 0 else 0.0,
            "hit_rate_pct": round(v["won"] / v["n"] * 100, 1) if v["n"] > 0 else 0.0,
        } for k, v in niche_agg.items()},
        "all_bets": all_bets,
        "params": {
            "flat_stake":              flat_stake,
            "min_training_per_league": min_training_per_league,
            "ev_threshold_b":          settings.ev_threshold_b,
            "disabled_niches":         settings.disabled_niches,
            "blacklist_combos":        settings.blacklist_combos,
        },
    }


if __name__ == "__main__":
    r = run_walkforward()
    if "error" in r:
        print(r["error"]); sys.exit(1)
    t = r["totals"]
    print(f"\n=== Walk-forward (out-of-sample) ===")
    print(f"Mois testés    : {t['n_months_tested']}")
    print(f"Paris OOS      : {t['n_bets']}")
    print(f"Hit rate       : {t['hit_rate_pct']}%")
    print(f"Mise totale    : {t['total_stake']:.2f} €")
    print(f"Profit total   : {t['total_profit']:+.2f} €")
    print(f"ROI OOS        : {t['roi_pct']:+.2f}%")
    print(f"\nPar mois :")
    for m in r["months"]:
        print(f"  {m['month']}: n={m['n_bets']:3d} ROI={m['roi_pct']:+6.2f}% profit={m['profit']:+8.2f} cumul={m['cumulative_profit']:+8.2f}")
    print(f"\nPar niche (OOS) :")
    for niche, st in sorted(r["by_niche"].items(), key=lambda x: -x[1]["roi_pct"]):
        print(f"  {niche:14s}: n={st['n']:4d} hit={st['hit_rate_pct']:5.1f}% ROI={st['roi_pct']:+6.2f}%")

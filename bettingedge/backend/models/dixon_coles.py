"""
Modèle Dixon-Coles — probabilités de scores foot.
Correction τ pour les faibles scores (0-0, 1-0, 0-1, 1-1).
"""
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    """Correction Dixon-Coles pour les scores faibles."""
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def predict(
    att_home: float,
    def_home: float,
    att_away: float,
    def_away: float,
    gamma: float = 1.20,
    rho: float = -0.13,
    max_goals: int = 10,
) -> np.ndarray:
    """
    Retourne matrice (max_goals × max_goals) de probabilités P(home=i, away=j).
    """
    lh = att_home * def_away * gamma
    la = att_away * def_home

    matrix = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson.pmf(i, lh) * poisson.pmf(j, la) * _tau(i, j, lh, la, rho)
            matrix[i, j] = p

    # Normaliser pour corriger le léger biais de τ
    total = matrix.sum()
    if total > 0:
        matrix /= total
    return matrix


def predict_from_params(home: str, away: str, params: dict, gamma: float = 1.20, rho: float = -0.13) -> np.ndarray:
    """Construit la matrice depuis les paramètres en BDD."""
    def _key(team: str) -> str:
        return team.lower().replace(" ", "_").replace("-", "_")

    att_home = params.get(f"att_{_key(home)}", 1.0)
    def_home = params.get(f"def_{_key(home)}", 1.0)
    att_away = params.get(f"att_{_key(away)}", 1.0)
    def_away = params.get(f"def_{_key(away)}", 1.0)
    gamma    = params.get("gamma", gamma)
    rho      = params.get("rho", rho)

    return predict(att_home, def_home, att_away, def_away, gamma, rho)


def prob_home_win(matrix: np.ndarray) -> float:
    return float(np.tril(matrix, -1).sum())


def prob_draw(matrix: np.ndarray) -> float:
    return float(np.trace(matrix))


def prob_away_win(matrix: np.ndarray) -> float:
    return float(np.triu(matrix, 1).sum())


def prob_btts(matrix: np.ndarray) -> float:
    """P(home ≥ 1 ET away ≥ 1)."""
    return float(matrix[1:, 1:].sum())


def prob_over(matrix: np.ndarray, threshold: float = 2.5) -> float:
    """P(total buts > threshold)."""
    n = matrix.shape[0]
    total = 0.0
    for i in range(n):
        for j in range(n):
            if i + j > threshold:
                total += matrix[i, j]
    return total


def prob_score(matrix: np.ndarray, home_goals: int, away_goals: int) -> float:
    if home_goals < matrix.shape[0] and away_goals < matrix.shape[1]:
        return float(matrix[home_goals, away_goals])
    return 0.0


def fit(match_history: list[dict]) -> dict:
    """
    Calibre att_i, def_i, gamma, rho via MLE.
    match_history : liste de dicts {home, away, home_goals, away_goals}
    Retourne dict de paramètres.
    """
    teams = list({m["home"] for m in match_history} | {m["away"] for m in match_history})
    team_idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    def neg_log_likelihood(params):
        att  = np.exp(params[:n])
        defe = np.exp(params[n:2*n])
        gamma = np.exp(params[2*n])
        rho   = np.tanh(params[2*n + 1]) * 0.5

        ll = 0.0
        for m in match_history:
            i, j = team_idx[m["home"]], team_idx[m["away"]]
            lh = att[i] * defe[j] * gamma
            la = att[j] * defe[i]
            hg, ag = m["home_goals"], m["away_goals"]
            tau = _tau(hg, ag, lh, la, rho)
            if tau <= 0 or lh <= 0 or la <= 0:
                continue
            ll += (poisson.logpmf(hg, lh) + poisson.logpmf(ag, la) + np.log(max(tau, 1e-10)))
        return -ll

    x0 = np.zeros(2 * n + 2)
    result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", options={"maxiter": 200})

    att  = np.exp(result.x[:n])
    defe = np.exp(result.x[n:2*n])
    gamma = float(np.exp(result.x[2*n]))
    rho   = float(np.tanh(result.x[2*n + 1]) * 0.5)

    out = {"gamma": round(gamma, 4), "rho": round(rho, 4)}
    for i, team in enumerate(teams):
        key = team.lower().replace(" ", "_").replace("-", "_")
        out[f"att_{key}"] = round(float(att[i]), 4)
        out[f"def_{key}"] = round(float(defe[i]), 4)

    return out

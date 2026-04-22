"""
Modèle Markov tennis — probabilités jeux, sets, match.
"""


def prob_game(p_server: float) -> float:
    """
    P(gagner un jeu au service) depuis p_server = P(gagner un point au service).
    Formule exacte jeu de tennis (états 0,15,30,40,deuce).
    """
    p = p_server
    q = 1 - p

    # P(gagner depuis deuce)
    p_deuce = p * p / (p * p + q * q)

    # P(gagner le jeu sans passer par deuce) + P(passer par deuce) × P(gagner depuis deuce)
    # Calcul exact : somme sur les chemins gagnants
    win = (
        p**4
        + 4 * (p**4) * q
        + 10 * (p**4) * (q**2)
        + 20 * (p**3) * (q**3) * p_deuce
    )
    return min(max(win, 0.0), 1.0)


def prob_tiebreak(p_a: float, p_b: float) -> float:
    """
    P(joueur A gagne le tie-break).
    p_a = P(A gagne un point sur son service), p_b = idem pour B.
    Approximation : moyenne des probabilités de point.
    """
    p_avg = (p_a + (1 - p_b)) / 2
    q_avg = 1 - p_avg

    # Tie-break : premier à 7 avec 2 d'écart
    # Approximation via formule fermée
    p_sd = p_avg * p_avg / (p_avg * p_avg + q_avg * q_avg)  # super-deuce

    win = sum(
        _comb(6 + k, k) * (p_avg ** 7) * (q_avg ** k)
        for k in range(7)
    ) + (p_avg ** 7) * (q_avg ** 6) * p_sd

    return min(max(win, 0.0), 1.0)


def prob_set(p_hold_a: float, p_hold_b: float) -> float:
    """
    P(A gagne un set) depuis les probabilités de tenir son service.
    p_hold_a = P(A tient son service), p_hold_b = idem pour B.
    """
    p_break_b = 1 - p_hold_b  # P(A breake B)
    p_break_a = 1 - p_hold_a  # P(B breake A)

    # Probabilité A gagne un jeu sur le service de B
    p_a_on_b_serve = p_break_b
    # Probabilité A gagne un jeu sur son propre service
    p_a_on_a_serve = p_hold_a

    # P(A gagne un jeu "moyen")
    p_game_avg = (p_a_on_a_serve + p_a_on_b_serve) / 2

    # Approximation set en 6 jeux avec tie-break
    q = 1 - p_game_avg
    win = sum(
        _comb(5 + k, k) * (p_game_avg ** 6) * (q ** k)
        for k in range(6)
    )

    # Tie-break à 6-6
    p_tb = p_game_avg ** 6 * q ** 6 * _comb(12, 6)
    # P(A gagne le tie-break) — approximation simple
    p_win_tb = p_game_avg  # si on considère prob uniforme sur le tie-break

    return min(max(win + p_tb * p_win_tb, 0.0), 1.0)


def prob_match(p_hold_a: float, p_hold_b: float, best_of: int = 3) -> float:
    """
    P(A gagne le match) en BO3 ou BO5.
    """
    sets_to_win = (best_of + 1) // 2
    p_set = prob_set(p_hold_a, p_hold_b)
    q_set = 1 - p_set

    win = 0.0
    for sets_won in range(sets_to_win, best_of + 1):
        sets_lost = sets_won - sets_to_win if sets_won == sets_to_win else sets_won - 1
        if sets_lost < 0:
            continue
        sets_lost = sets_won - sets_to_win
        total_sets = sets_won + sets_lost
        # Dernier set forcément gagné par A
        win += _comb(total_sets - 1, sets_won - 1) * (p_set ** sets_won) * (q_set ** sets_lost)

    return min(max(win, 0.0), 1.0)


def expected_service_games(p_hold_a: float, p_hold_b: float, best_of: int = 3) -> float:
    """
    E[nombre de jeux de service dans le match] — utilisé pour λ_aces Poisson.
    Approximation : E[jeux totaux] × 0.5 (chaque joueur sert ~50% des jeux).
    """
    # E[sets] ≈ best_of - 0.5 pour un match équilibré
    p_set = prob_set(p_hold_a, p_hold_b)
    q_set = 1 - p_set
    sets_to_win = (best_of + 1) // 2

    e_sets = 0.0
    for n_sets in range(sets_to_win, best_of + 1):
        sets_lost = n_sets - sets_to_win
        total = n_sets + sets_lost
        prob = _comb(total - 1, sets_lost) * (
            p_set ** n_sets * q_set ** sets_lost
            + q_set ** n_sets * p_set ** sets_lost
        )
        e_sets += total * prob

    # E[jeux par set] ≈ 9.5 (empirique)
    e_games = e_sets * 9.5
    return e_games * 0.5  # jeux de service pour chaque joueur


def _comb(n: int, k: int) -> float:
    from math import comb
    if k < 0 or k > n:
        return 0.0
    return float(comb(n, k))

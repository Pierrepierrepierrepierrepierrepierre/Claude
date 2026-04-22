"""De-vigging multiplicatif — extraction de la probabilité réelle depuis les cotes."""


def devig(odds: list[float]) -> list[float]:
    """
    Retourne les probabilités normalisées (sans marge bookmaker).
    odds : liste de cotes décimales pour un marché (ex: [2.1, 3.4, 3.2] pour 1X2)
    """
    if not odds or any(o <= 1 for o in odds):
        return []
    implied = [1 / o for o in odds]
    total = sum(implied)
    return [round(p / total, 6) for p in implied]


def vig(odds: list[float]) -> float:
    """Marge bookmaker = Σ(1/cote) - 1."""
    if not odds:
        return 0.0
    return round(sum(1 / o for o in odds) - 1, 4)


def consensus(
    odds_1x2: list[float],
    odds_ah: list[float] = None,
    odds_ou: list[float] = None,
    weights: list[float] = None,
) -> list[float]:
    """
    Consensus multi-marchés : moyenne pondérée des probabilités de-vigged.
    Retourne [p_home, p_draw, p_away] si 1X2 fourni.
    """
    sources = []
    if odds_1x2 and len(odds_1x2) == 3:
        sources.append(devig(odds_1x2))
    if odds_ah and len(odds_ah) == 2:
        p_ah = devig(odds_ah)
        sources.append([p_ah[0], 0.0, p_ah[1]])
    if odds_ou and len(odds_ou) == 2:
        p_ou = devig(odds_ou)
        sources.append([p_ou[0], 0.0, p_ou[1]])

    if not sources:
        return []

    w = weights or [1.0] * len(sources)
    total_w = sum(w[:len(sources)])

    result = [0.0, 0.0, 0.0]
    for i, src in enumerate(sources):
        for j in range(min(3, len(src))):
            result[j] += src[j] * w[i] / total_w

    # Renormaliser
    s = sum(result)
    if s > 0:
        result = [round(r / s, 6) for r in result]

    return result

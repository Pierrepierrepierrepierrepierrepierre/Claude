"""
Calcule l'évolution des cotes Betclic depuis OddsHistory.
Pour un même event_id, compare le 1er et le dernier snapshot.

Utilisation typique : afficher dans le dashboard "cote 1.85 → 1.78 (-3.8%)
sur 3 snapshots depuis hier" pour chaque recommandation.
"""
from sqlalchemy.orm import Session
from backend.db.models import OddsHistory


# Champs de cotes possibles dans OddsHistory
ODDS_FIELDS = (
    "odds_home", "odds_draw", "odds_away",
    "odds_ah_home", "odds_ah_away",
    "odds_ou_over", "odds_ou_under",
    "boost_odds",
)


def get_event_snapshots(db: Session, event_id: str, market_type: str = "1X2") -> list[OddsHistory]:
    """Renvoie tous les snapshots d'un événement, triés du plus ancien au plus récent."""
    return (
        db.query(OddsHistory)
        .filter_by(event_id=event_id, market_type=market_type)
        .order_by(OddsHistory.scraped_at.asc())
        .all()
    )


def _match_field_for_value(snapshot: OddsHistory, target_value: float, tol: float = 0.01) -> str | None:
    """Trouve le champ de cote dont la valeur correspond à `target_value`."""
    if target_value is None:
        return None
    for field in ODDS_FIELDS:
        v = getattr(snapshot, field, None)
        if v is not None and abs(v - target_value) < tol:
            return field
    return None


def compute_variation(
    db: Session,
    event_id: str,
    odds_betclic: float,
    market_type: str = "1X2",
) -> dict | None:
    """
    Calcule la variation entre 1er et dernier snapshot pour la cote `odds_betclic`.

    Renvoie {first, last, delta_abs, delta_pct, n_snapshots, field, span_hours}
    ou None si on n'a pas au moins 2 snapshots ou pas de match de champ.
    """
    snapshots = get_event_snapshots(db, event_id, market_type)
    if len(snapshots) < 2:
        return None

    last = snapshots[-1]
    first = snapshots[0]

    # On identifie le champ depuis le snapshot le plus récent (mêmes valeurs que la reco)
    field = _match_field_for_value(last, odds_betclic)
    if field is None:
        return None

    first_val = getattr(first, field, None)
    last_val = getattr(last, field, None)
    if first_val is None or last_val is None or first_val == 0:
        return None

    delta_abs = round(last_val - first_val, 3)
    delta_pct = round((last_val / first_val - 1) * 100, 2)

    # Durée couverte par les snapshots
    try:
        from datetime import datetime
        t_first = datetime.fromisoformat(first.scraped_at.replace("Z", "+00:00"))
        t_last = datetime.fromisoformat(last.scraped_at.replace("Z", "+00:00"))
        span_hours = round((t_last - t_first).total_seconds() / 3600, 1)
    except Exception:
        span_hours = None

    return {
        "first": first_val,
        "last": last_val,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "n_snapshots": len(snapshots),
        "field": field,
        "span_hours": span_hours,
        "first_at": first.scraped_at,
        "last_at": last.scraped_at,
    }


def latest_snapshot_before(
    db: Session, event_id: str, before_iso: str, market_type: str = "1X2"
) -> OddsHistory | None:
    """Dernier snapshot pris AVANT `before_iso` — utile pour récupérer la cote
    de clôture Betclic (ex: dernière cote vue avant kickoff)."""
    return (
        db.query(OddsHistory)
        .filter(
            OddsHistory.event_id == event_id,
            OddsHistory.market_type == market_type,
            OddsHistory.scraped_at < before_iso,
        )
        .order_by(OddsHistory.scraped_at.desc())
        .first()
    )

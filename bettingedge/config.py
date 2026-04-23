from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    port: int = 8000
    db_path: str = "bettingedge.db"
    log_level: str = "INFO"

    scrape_window_min: int = -15
    scrape_window_max: int = 30

    kelly_kappa: float = 0.25
    max_stake_pct: float = 0.05
    capital_initial: float = 1000.0

    ev_threshold_a: float = 0.03
    # Strategy B : seuil EV minimum pour parier
    # Calibré à 0.10 suite à l'analyse backtest (commit ddab33b) :
    #   tranches EV 2-5% perdent -12%, EV 25%+ gagnent +15%. Le seuil 0.10
    #   coupe ~80% des paris perdants et garde ~80% du profit.
    ev_threshold_b: float = 0.10
    brier_alert_threshold: float = 0.22

    # Safety caps (mitigation des biais identifiés en backtest)
    # ev_cap : au-dessus, on considère que le modèle déraille → skip
    # ev_threshold_draw_extra : surcoût EV exigé pour parier "Nul"
    #   (le DC simplifié sur-estime les nuls de ~5-8 points → on compense)
    ev_cap: float = 0.50
    ev_threshold_draw_extra: float = 0.15

    # Niches désactivées dans le pipeline (le backtest les a montrées
    # systématiquement perdantes — ROI -7%). Format : préfixe (startswith).
    disabled_niches: list[str] = ["under_"]

    # Combos niche × ligue à blacklister (ROI < -4% sur ≥ 100 paris en backtest).
    # Format : "niche:league" (league = clé du dict LEAGUES de fbref.py).
    blacklist_combos: list[str] = [
        "1x2_draw:serie_a",
        "1x2_away:bundesliga",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

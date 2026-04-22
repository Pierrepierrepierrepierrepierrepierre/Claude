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
    ev_threshold_b: float = 0.02
    brier_alert_threshold: float = 0.22

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

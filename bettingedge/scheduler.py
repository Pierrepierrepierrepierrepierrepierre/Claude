"""
APScheduler — jobs quotidiens de scraping et recalibration.
Démarré via le lifespan FastAPI (mode prod uniquement).
"""
import random
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def _rand_minute(base: int, window_min: int = -15, window_max: int = 30) -> int:
    offset = random.randint(window_min, window_max)
    return max(0, min(59, base + offset))


def make_scheduler() -> BackgroundScheduler:
    from backend.scrapers.fbref import scrape_all as scrape_fbref
    from backend.scrapers.tennis_abstract import scrape_all as scrape_tennis
    from backend.scrapers.betclic import run as scrape_betclic
    from backend.db.backup import backup

    scheduler = BackgroundScheduler(timezone="Europe/Paris")

    # Backup à ~05h40 (avant tout scraping)
    scheduler.add_job(backup, CronTrigger(hour=5, minute=_rand_minute(40, -5, 10)), id="backup")

    # FBref à ~06h00
    scheduler.add_job(scrape_fbref, CronTrigger(hour=6, minute=_rand_minute(0)), id="fbref")

    # Tennis Abstract à ~06h15
    scheduler.add_job(scrape_tennis, CronTrigger(hour=6, minute=_rand_minute(15)), id="tennis_abstract")

    # Betclic à ~06h30 (après les stats)
    scheduler.add_job(scrape_betclic, CronTrigger(hour=6, minute=_rand_minute(30)), id="betclic")

    return scheduler

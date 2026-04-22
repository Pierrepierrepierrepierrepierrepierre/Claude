"""
Scraper Betclic — cotes foot/tennis + Super Boosts.
Playwright headed, session persistante, anti-détection.
Usage : python -m backend.scrapers.betclic
"""
import asyncio
import random
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.db.database import SessionLocal
from backend.db.crud import log_scraper
from backend.db.models import OddsHistory
from backend.db.backup import backup

SESSION_FILE = Path("betclic_session.json")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BETCLIC_FOOTBALL_URL = "https://www.betclic.fr/football-s1"
BETCLIC_TENNIS_URL   = "https://www.betclic.fr/tennis-s2"
BETCLIC_BOOSTS_URL   = "https://www.betclic.fr/super-boosts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rand_sleep(low: float = 3.0, high: float = 8.0):
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(random.uniform(low, high)))


async def _async_sleep(low: float = 3.0, high: float = 8.0):
    await asyncio.sleep(random.uniform(low, high))


def _is_captcha(page_content: str) -> bool:
    markers = ["captcha", "robot", "je ne suis pas un robot", "recaptcha", "cloudflare"]
    content_lower = page_content.lower()
    return any(m in content_lower for m in markers)


async def scrape(headless: bool = False) -> dict:
    """Lance le scraping Betclic. Retourne dict avec cotes et boosts."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "playwright non installé — lance: playwright install chromium"}

    ua = random.choice(USER_AGENTS)
    results = {"football": [], "tennis": [], "boosts": [], "error": None}

    async with async_playwright() as p:
        # Charger session existante si disponible
        storage = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else None

        browser = await p.chromium.launch(headless=headless)
        ctx_args = {"user_agent": ua}
        if storage:
            ctx_args["storage_state"] = storage

        context = await browser.new_context(**ctx_args)
        page = await context.new_page()

        try:
            # --- Super Boosts ---
            await page.goto(BETCLIC_BOOSTS_URL, timeout=30000)
            await _async_sleep(2, 5)

            content = await page.content()
            if _is_captcha(content):
                results["error"] = "captcha"
                await browser.close()
                return results

            # Parser les boosts (sélecteurs à adapter selon la structure réelle)
            boost_els = await page.query_selector_all("[class*='boost'], [class*='super']")
            for el in boost_els[:20]:
                try:
                    text = await el.inner_text()
                    results["boosts"].append({"raw": text.strip(), "scraped_at": _now()})
                except Exception:
                    pass

            await _async_sleep()

            # --- Football ---
            await page.goto(BETCLIC_FOOTBALL_URL, timeout=30000)
            await _async_sleep(2, 5)

            content = await page.content()
            if _is_captcha(content):
                results["error"] = "captcha"
                await browser.close()
                return results

            # Parser les événements foot
            event_els = await page.query_selector_all("[class*='event'], [class*='match']")
            for el in event_els[:30]:
                try:
                    text = await el.inner_text()
                    odds_els = await el.query_selector_all("[class*='odd'], [class*='cote'], button")
                    odds = []
                    for o in odds_els[:3]:
                        try:
                            v = await o.inner_text()
                            val = float(v.strip().replace(",", "."))
                            if 1.01 <= val <= 50:
                                odds.append(val)
                        except Exception:
                            pass
                    if odds:
                        results["football"].append({"event": text[:100], "odds": odds, "scraped_at": _now()})
                except Exception:
                    pass

            await _async_sleep()

            # Sauvegarder la session
            storage_state = await context.storage_state()
            SESSION_FILE.write_text(json.dumps(storage_state))

        except Exception as e:
            results["error"] = str(e)
        finally:
            await browser.close()

    return results


def save_odds(results: dict):
    """Sauvegarde les cotes en BDD."""
    db = SessionLocal()
    saved = 0
    try:
        for item in results.get("football", []):
            odds = item.get("odds", [])
            if len(odds) >= 3:
                event_id = item["event"][:50].strip().lower().replace(" ", "_")
                for i, (market, odd) in enumerate(zip(["1", "X", "2"], odds)):
                    db.add(OddsHistory(
                        event_id=event_id,
                        market=f"1X2_{market}",
                        odds=odd,
                        recorded_at=item["scraped_at"],
                    ))
                    saved += 1

        db.commit()
    finally:
        db.close()
    return saved


def run(headless: bool = False) -> bool:
    backup()  # Backup BDD avant scraping

    db = SessionLocal()
    try:
        results = asyncio.run(scrape(headless=headless))

        if results.get("error") == "captcha":
            log_scraper(db, "betclic", "captcha", "CAPTCHA détecté — saisie manuelle requise")
            print("CAPTCHA détecté. Utilise /api/strategy-a/calculate pour saisie manuelle.")
            return False

        if results.get("error"):
            log_scraper(db, "betclic", "error", results["error"])
            return False

        saved = save_odds(results)
        n_boosts = len(results["boosts"])
        msg = f"{saved} cotes, {n_boosts} boosts détectés"
        log_scraper(db, "betclic", "ok", msg)
        print(f"Betclic OK — {msg}")
        return True

    except Exception as e:
        log_scraper(db, "betclic", "error", str(e))
        print(f"ERREUR: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    run(headless=headless)

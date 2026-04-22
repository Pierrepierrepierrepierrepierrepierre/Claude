"""
Scraper Betclic — interception réseau Playwright.
Récupère les vrais matchs du jour avec cotes structurées (1X2, AH, O/U, boosts).
Anti-ban : headed, UA rotation, session persistante, délais aléatoires.
"""
import asyncio
import random
import json
import sys
import os
import re
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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# URLs à scraper — page principale + compétitions européennes prioritaires
URLS = {
    "football": "https://www.betclic.fr/football-s1",
    "tennis":   "https://www.betclic.fr/tennis-s2",
    "boosts":   "https://www.betclic.fr/sport/super-boosts",
}

# Compétitions européennes à scraper en supplément
# Slugs découverts dynamiquement sur betclic.fr (format: football-sfootball/{slug})
COMPETITION_URLS = [
    "https://www.betclic.fr/football-sfootball/ligue-1-mcdonald-s-c4",
    "https://www.betclic.fr/football-sfootball/angl-premier-league-c3",
    "https://www.betclic.fr/football-sfootball/la-liga-c16",
    "https://www.betclic.fr/football-sfootball/serie-a-italienne-c15",
    "https://www.betclic.fr/football-sfootball/bundesliga-c14",
    "https://www.betclic.fr/football-sfootball/ligue-des-champions-c2",
    "https://www.betclic.fr/football-sfootball/europa-league-c5",
]

# Patterns des appels API internes de Betclic (interceptés via réseau)
API_PATTERNS = [
    "/sport/", "/events", "/competitions", "/markets",
    "api.betclic", "apiv", "/v4/", "/v3/",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_captcha(content: str) -> bool:
    return any(m in content.lower() for m in ["captcha", "robot", "recaptcha", "cloudflare challenge"])


def _extract_odds_from_text(text: str) -> list[float]:
    """Extrait les cotes décimales d'un bloc de texte."""
    candidates = re.findall(r'\b(\d+[.,]\d{1,2})\b', text)
    odds = []
    for c in candidates:
        try:
            v = float(c.replace(",", "."))
            if 1.01 <= v <= 99.0:
                odds.append(v)
        except ValueError:
            pass
    return odds


async def _scrape_page_events(page, sport: str) -> list[dict]:
    """
    Scrape une page Betclic en combinant :
    1. Interception des réponses JSON de l'API interne
    2. Parsing DOM de secours (sélecteurs robustes)
    """
    events = []
    api_data = []

    # Intercepteur de réponses réseau
    async def on_response(response):
        url = response.url
        if response.status == 200 and any(p in url for p in API_PATTERNS):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    data = await response.json()
                    api_data.append({"url": url, "data": data})
            except Exception:
                pass

    page.on("response", on_response)

    await page.goto(URLS[sport], timeout=60000, wait_until="domcontentloaded")
    # Attendre que le contenu dynamique soit chargé (SPA React)
    await asyncio.sleep(random.uniform(5, 8))

    content = await page.content()
    # Captcha réel : page de challenge (pas juste le widget reCaptcha embarqué)
    if _is_captcha(content) and len(content) < 50000:
        return [{"__captcha": True}]

    # Tentative 1 : parser les données JSON interceptées
    if api_data:
        events.extend(_parse_api_responses(api_data, sport))

    # Tentative 2 : DOM parsing via sports-events-event-card
    if not events:
        events.extend(await _parse_dom_events(page, sport))

    return events


def _parse_api_responses(api_data: list[dict], sport: str) -> list[dict]:
    """
    Parse les réponses JSON de l'API Betclic pour extraire les matchs.
    L'API Betclic retourne des structures avec "events", "competitions" ou "markets".
    """
    events = []

    def _find_events(obj, depth=0):
        if depth > 8 or not isinstance(obj, (dict, list)):
            return

        if isinstance(obj, list):
            for item in obj:
                _find_events(item, depth + 1)
            return

        # Chercher des patterns typiques d'un événement sportif
        name = obj.get("name") or obj.get("eventName") or obj.get("label") or ""
        home = obj.get("homeTeamName") or obj.get("home_team") or obj.get("homeTeam") or ""
        away = obj.get("awayTeamName") or obj.get("away_team") or obj.get("awayTeam") or ""

        # Betclic structure typique : event avec markets
        if (home and away) or (" - " in name and len(name) > 5):
            evt_name = f"{home} - {away}" if (home and away) else name
            event_date = (obj.get("startDate") or obj.get("date") or
                         obj.get("eventDate") or obj.get("startTime") or "")
            event_id = str(obj.get("id") or obj.get("eventId") or
                          obj.get("uid") or hash(evt_name))
            league = obj.get("competition") or obj.get("competitionName") or obj.get("league") or ""

            # Extraire les cotes
            odds_1x2 = [None, None, None]
            odds_ah = [None, None]
            odds_ou = [None, None]

            markets = obj.get("markets") or obj.get("selections") or []
            if isinstance(markets, list):
                for mkt in markets:
                    mkt_name = (mkt.get("name") or mkt.get("marketName") or "").lower()
                    selections = mkt.get("selections") or mkt.get("runners") or []
                    if not isinstance(selections, list):
                        continue

                    sel_odds = []
                    for sel in selections:
                        price = (sel.get("price") or sel.get("odds") or
                                sel.get("decimal") or sel.get("value") or 0)
                        try:
                            sel_odds.append(float(price))
                        except (ValueError, TypeError):
                            pass

                    if "1x2" in mkt_name or "match result" in mkt_name or "résultat" in mkt_name:
                        if len(sel_odds) >= 3:
                            odds_1x2 = sel_odds[:3]
                    elif "asian" in mkt_name or "handicap" in mkt_name:
                        if len(sel_odds) >= 2:
                            odds_ah = sel_odds[:2]
                    elif "over" in mkt_name or "under" in mkt_name or "total" in mkt_name:
                        if len(sel_odds) >= 2:
                            odds_ou = sel_odds[:2]

            if any(o for o in odds_1x2 if o):
                events.append({
                    "event_id":   str(event_id),
                    "event_name": evt_name,
                    "home_team":  home or evt_name.split(" - ")[0],
                    "away_team":  away or (evt_name.split(" - ")[1] if " - " in evt_name else ""),
                    "event_date": str(event_date)[:19] if event_date else None,
                    "sport":      sport,
                    "league":     str(league)[:100] if league else "",
                    "odds_home":  odds_1x2[0],
                    "odds_draw":  odds_1x2[1],
                    "odds_away":  odds_1x2[2],
                    "odds_ah_home": odds_ah[0],
                    "odds_ah_away": odds_ah[1],
                    "odds_ou_over": odds_ou[0],
                    "odds_ou_under": odds_ou[1],
                })
            else:
                # Descendre récursivement
                for key in ("events", "competitions", "markets", "children", "items"):
                    if key in obj:
                        _find_events(obj[key], depth + 1)
            return

        # Pas un événement → descendre
        for key in ("events", "competitions", "markets", "children", "items",
                    "data", "result", "response", "payload"):
            if key in obj:
                _find_events(obj[key], depth + 1)

    for item in api_data:
        _find_events(item.get("data", {}))

    return events


async def _parse_dom_events(page, sport: str) -> list[dict]:
    """
    Parse les matchs Betclic depuis les custom elements 'sports-events-event-card'.

    Structure d'un card (texte extrait ligne par ligne) :
    Live :    [competition, "44' - MT 1", home_short, score_h, "-", score_a, away_short,
               home_full…, odds_home, "Nul", odds_draw, away_full…, odds_away]
    Upcoming: [competition, "+N", "paris"?, home_short, "HH:MM", away_short,
               home_full…, odds_home, "Nul", odds_draw, away_full…, odds_away]

    Ancre fiable : "Nul" est toujours entre odds_home et odds_draw.
    """
    events = []
    cards = await page.query_selector_all("sports-events-event-card")
    if not cards:
        return events

    for card in cards:
        try:
            a_el = await card.query_selector("a")
            href = await a_el.get_attribute("href") if a_el else ""

            # Match ID depuis l'URL : /xxx/home-away-m<id>
            mid_match = re.search(r"-m(\d+)", href or "")
            event_id = mid_match.group(1) if mid_match else re.sub(r"[^a-z0-9]", "_", (href or ""))[:40]

            # Date de l'événement depuis href slug si possible
            event_date = None

            text = await card.inner_text()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) < 4:
                continue

            def to_float(s: str) -> float | None:
                try:
                    v = float(s.replace(",", "."))
                    return v if 1.01 <= v <= 100 else None
                except (ValueError, AttributeError):
                    return None

            def to_float(s: str) -> float | None:
                try:
                    if s.startswith("+") or s.startswith("-"):
                        return None  # "+65 paris" = nombre de marchés, pas une cote
                    v = float(s.replace(",", "."))
                    return v if 1.01 <= v <= 50 else None
                except (ValueError, AttributeError):
                    return None

            # Football : ancre "Nul" → 3 cotes (domicile / nul / extérieur)
            nul_idx = next((i for i, l in enumerate(lines) if l == "Nul"), None)

            # Index de l'heure HH:MM (présent dans les matchs programmés)
            time_idx = next(
                (i for i, l in enumerate(lines) if re.match(r"^\d{2}:\d{2}$", l)), None
            )

            if sport == "football":
                if nul_idx is None:
                    continue
                odds_home = None
                for i in range(nul_idx - 1, -1, -1):
                    v = to_float(lines[i])
                    if v:
                        odds_home = v
                        break
                floats_after = [to_float(lines[i]) for i in range(nul_idx + 1, len(lines))]
                floats_after = [v for v in floats_after if v]
                odds_draw = floats_after[0] if floats_after else None
                odds_away = floats_after[1] if len(floats_after) > 1 else None
                if not (odds_home and odds_draw and odds_away):
                    continue
            else:
                # Tennis : 2 cotes seulement, collectées après l'heure (ou après le joueur away)
                start = (time_idx + 2) if time_idx is not None else 3
                tennis_odds = [to_float(lines[i]) for i in range(start, len(lines))]
                tennis_odds = [v for v in tennis_odds if v]
                if len(tennis_odds) < 2:
                    continue
                odds_home = tennis_odds[0]
                odds_draw = None
                odds_away = tennis_odds[1]

            # --- Extraire noms d'équipes ---
            # Ligne 0 = competition ; chercher home/away autour de l'heure ou du score
            league = lines[0] if lines else ""

            # Détecter si live (contient "'") ou scheduled (contient ":")
            is_live = any("'" in l for l in lines[:4])

            home_name = ""
            away_name = ""
            event_time = ""

            if is_live:
                # Live: [comp, "44' - MT 1", home_short, score_h, "-", score_a, away_short, …]
                home_name = lines[2] if len(lines) > 2 else ""
                # away_short = first non-digit, non-"-" line after the score block
                score_end = 6  # position typique
                for i in range(3, min(8, len(lines))):
                    if lines[i] == "-":
                        score_end = i + 2  # away_short suit le score away
                        break
                away_name = lines[score_end] if len(lines) > score_end else ""
            else:
                # Scheduled : [comp, "+N"?, "paris"?, home_short, "HH:MM", away_short, …]
                time_idx = next(
                    (i for i, l in enumerate(lines) if re.match(r"^\d{2}:\d{2}$", l)),
                    None
                )
                if time_idx and time_idx >= 1:
                    home_name = lines[time_idx - 1]
                    away_name = lines[time_idx + 1] if len(lines) > time_idx + 1 else ""
                    event_time = lines[time_idx]

            if not home_name or not away_name:
                continue

            event_name = f"{home_name} - {away_name}"

            events.append({
                "event_id":    event_id,
                "event_name":  event_name,
                "event_date":  event_time or None,
                "sport":       sport,
                "league":      league,
                "odds_home":   odds_home,
                "odds_draw":   odds_draw,
                "odds_away":   odds_away,
                "odds_ah_home":  None,
                "odds_ah_away":  None,
                "odds_ou_over":  None,
                "odds_ou_under": None,
            })

        except Exception as e:
            print(f"  [warn] card parse error: {e}")
            continue

    return events


async def _scrape_competition_page(page, url: str) -> list[dict]:
    """Scrape une page de compétition spécifique (Ligue 1, PL, etc.)."""
    try:
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(4, 6))
        content = await page.content()
        if _is_captcha(content) and len(content) < 50000:
            return []
        return await _parse_dom_events(page, "football")
    except Exception:
        return []


async def _scrape_boosts(page) -> list[dict]:
    """
    Scrape la page Super Boosts.
    Retourne la liste des boosts avec event_name, boost_odds, normal_odds.
    """
    boosts = []
    api_data = []

    async def on_response(response):
        url = response.url
        if response.status == 200 and any(p in url for p in API_PATTERNS + ["boost", "promo"]):
            try:
                if "json" in response.headers.get("content-type", ""):
                    data = await response.json()
                    api_data.append({"url": url, "data": data})
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(URLS["boosts"], timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2, 4))
    except Exception:
        return boosts

    content = await page.content()
    if _is_captcha(content):
        return [{"__captcha": True}]

    # Parsing DOM des boosts (structure plus simple que les matchs)
    boost_selectors = [
        "[class*='boost']",
        "[class*='superBoost']",
        "[class*='promo']",
        "[data-testid*='boost']",
    ]

    for selector in boost_selectors:
        try:
            elements = await page.query_selector_all(selector)
            for el in elements[:15]:
                try:
                    text = await el.inner_text()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    odds = _extract_odds_from_text(text)

                    # Un boost a généralement 2 cotes visibles (normale + boostée)
                    # ou une seule cote boostée avec le label "boosté"
                    event_name = next((l for l in lines if len(l) > 5 and not re.match(r"^\d", l)), "")

                    if event_name and odds:
                        boost_odds = max(odds)  # la cote boostée est généralement la plus haute
                        normal_odds = min(odds) if len(odds) >= 2 else None
                        boosts.append({
                            "event_name": event_name[:100],
                            "boost_odds": boost_odds,
                            "normal_odds": normal_odds,
                            "raw_text": text[:200],
                        })
                except Exception:
                    continue
        except Exception:
            continue

    return boosts


async def scrape_all(headless: bool = False) -> dict:
    """Lance le scraping complet Betclic. Retourne dict structuré."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "playwright non installé"}

    ua = random.choice(USER_AGENTS)
    results = {"football": [], "tennis": [], "boosts": [], "error": None}

    async with async_playwright() as p:
        storage = None
        if SESSION_FILE.exists():
            try:
                storage = json.loads(SESSION_FILE.read_text())
            except Exception:
                pass

        browser = await p.chromium.launch(headless=headless)
        ctx_args = {
            "user_agent": ua,
            "viewport": {"width": 1366, "height": 768},
            "locale": "fr-FR",
        }
        if storage:
            ctx_args["storage_state"] = storage

        context = await browser.new_context(**ctx_args)
        page = await context.new_page()

        # Masquer les indicateurs Playwright
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            # Commencer par la page principale pour établir la session
            print("Chargement page principale Betclic...")
            try:
                await page.goto("https://www.betclic.fr", timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(3, 5))
                # Accepter les cookies si présents
                for btn_sel in ["[data-label*='accepter']", "[id*='accept']", "button[class*='accept']",
                                "[aria-label*='Accept']", "button:has-text('Accepter')"]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn:
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass
            except Exception as e:
                print(f"  Page principale : {e}")

            print("Scraping football — page principale...")
            football = await _scrape_page_events(page, "football")
            if football and football[0].get("__captcha"):
                results["error"] = "captcha"
                await browser.close()
                return results
            results["football"] = [e for e in football if not e.get("__captcha")]
            print(f"  {len(results['football'])} matchs foot page principale")

            # Scraper les compétitions européennes prioritaires
            seen_ids = {e["event_id"] for e in results["football"]}
            for comp_url in COMPETITION_URLS:
                try:
                    await asyncio.sleep(random.uniform(2, 4))
                    comp_events = await _scrape_competition_page(page, comp_url)
                    new_events = [e for e in comp_events if e.get("event_id") not in seen_ids]
                    results["football"].extend(new_events)
                    seen_ids.update(e["event_id"] for e in new_events)
                    if new_events:
                        print(f"  +{len(new_events)} matchs depuis {comp_url.split('/')[-1]}")
                except Exception as e:
                    print(f"  [warn] {comp_url.split('/')[-1]}: {e}")

            print(f"  Total foot: {len(results['football'])} matchs")
            await asyncio.sleep(random.uniform(4, 8))

            print("Scraping tennis...")
            tennis = await _scrape_page_events(page, "tennis")
            if tennis and tennis[0].get("__captcha"):
                print("  CAPTCHA tennis — skipped")
            else:
                results["tennis"] = [e for e in tennis if not e.get("__captcha")]
            print(f"  {len(results['tennis'])} matchs tennis")

            await asyncio.sleep(random.uniform(4, 8))

            print("Scraping boosts...")
            try:
                boosts = await _scrape_boosts(page)
                results["boosts"] = [b for b in boosts if not b.get("__captcha")]
            except Exception:
                results["boosts"] = []
            print(f"  {len(results['boosts'])} boosts trouvés")

            # Sauvegarder session
            state = await context.storage_state()
            SESSION_FILE.write_text(json.dumps(state))

        except Exception as e:
            results["error"] = str(e)
        finally:
            await browser.close()

    return results


def save_to_db(results: dict) -> int:
    """Sauvegarde les matchs scrapés en BDD dans OddsHistory."""
    db = SessionLocal()
    saved = 0
    try:
        scraped_at = _now()

        for sport in ["football", "tennis"]:
            for evt in results.get(sport, []):
                if not evt.get("event_name"):
                    continue

                db.add(OddsHistory(
                    event_id     = evt["event_id"],
                    event_name   = evt["event_name"],
                    event_date   = evt.get("event_date"),
                    sport        = sport,
                    league       = evt.get("league", ""),
                    market_type  = "1X2",
                    odds_home    = evt.get("odds_home"),
                    odds_draw    = evt.get("odds_draw"),
                    odds_away    = evt.get("odds_away"),
                    odds_ah_home = evt.get("odds_ah_home"),
                    odds_ah_away = evt.get("odds_ah_away"),
                    odds_ou_over = evt.get("odds_ou_over"),
                    odds_ou_under= evt.get("odds_ou_under"),
                    is_boost     = False,
                    scraped_at   = scraped_at,
                ))
                saved += 1

        # Boosts : associer à des événements existants ou créer entrée dédiée
        for boost in results.get("boosts", []):
            event_name = boost.get("event_name", "Boost inconnu")
            event_id = re.sub(r"[^a-z0-9]", "_", event_name.lower())[:60]
            db.add(OddsHistory(
                event_id    = f"boost_{event_id}",
                event_name  = event_name,
                sport       = "football",  # défaut, sera affiné
                market_type = "BOOST",
                is_boost    = True,
                boost_odds  = boost.get("boost_odds"),
                normal_odds = boost.get("normal_odds"),
                scraped_at  = scraped_at,
            ))
            saved += 1

        db.commit()
    finally:
        db.close()
    return saved


def run(headless: bool = False) -> bool:
    backup()
    db = SessionLocal()
    try:
        results = asyncio.run(scrape_all(headless=headless))

        if results.get("error") == "captcha":
            log_scraper(db, "betclic", "captcha", "CAPTCHA détecté — saisie manuelle requise")
            print("CAPTCHA détecté.")
            return False

        if results.get("error"):
            log_scraper(db, "betclic", "error", results["error"])
            return False

        saved = save_to_db(results)

        # Lancer le pipeline d'analyse après le scraping
        n_foot = len(results["football"])
        n_tennis = len(results["tennis"])
        n_boosts = len(results["boosts"])

        try:
            from backend.pipeline import run_pipeline
            db2 = SessionLocal()
            n_reco = run_pipeline(db2)
            db2.close()
            print(f"Pipeline : {n_reco} recommandations générées")
        except Exception as e:
            print(f"Pipeline (non bloquant) : {e}")

        msg = f"{n_foot} matchs foot, {n_tennis} matchs tennis, {n_boosts} boosts, {saved} enregistrements"
        log_scraper(db, "betclic", "ok", msg)
        print(f"Betclic OK — {msg}")
        return True

    except Exception as e:
        log_scraper(db, "betclic", "error", str(e))
        return False
    finally:
        db.close()


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    run(headless=headless)

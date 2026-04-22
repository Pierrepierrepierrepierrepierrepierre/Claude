"""
Normalisation des noms d'équipes et de joueurs.
Betclic utilise des noms localisés (français) ; football-data.co.uk utilise
des noms anglais courts. Ce module fait le pont via un dictionnaire + fuzzy
matching difflib.

Clés cibles : conventions football-data.co.uk telles que produites par
backend/scrapers/fbref.py (lower, espaces→_, tirets→_). Exemples :
"paris_sg", "ath_madrid", "man_city", "nott'm_forest", "m'gladbach".
"""
import unicodedata
import re
from difflib import get_close_matches

TEAM_MAP: dict[str, str] = {
    # ── Ligue 1 ─────────────────────────────────────────────────────────────
    "paris saint-germain":       "paris_sg",
    "psg":                       "paris_sg",
    "paris sg":                  "paris_sg",
    "paris fc":                  "paris_fc",
    "olympique de marseille":    "marseille",
    "marseille":                 "marseille",
    "om":                        "marseille",
    "olympique lyonnais":        "lyon",
    "lyon":                      "lyon",
    "ol":                        "lyon",
    "as monaco":                 "monaco",
    "monaco":                    "monaco",
    "stade rennais":             "rennes",
    "rennes":                    "rennes",
    "rc lens":                   "lens",
    "lens":                      "lens",
    "losc lille":                "lille",
    "lille":                     "lille",
    "ogc nice":                  "nice",
    "nice":                      "nice",
    "stade de reims":            "reims",
    "reims":                     "reims",
    "rc strasbourg":             "strasbourg",
    "strasbourg":                "strasbourg",
    "fc nantes":                 "nantes",
    "nantes":                    "nantes",
    "fc lorient":                "lorient",
    "lorient":                   "lorient",
    "toulouse fc":               "toulouse",
    "toulouse":                  "toulouse",
    "montpellier":               "montpellier",
    "stade brestois":            "brest",
    "brest":                     "brest",
    "havre ac":                  "le_havre",
    "le havre":                  "le_havre",
    "metz":                      "metz",
    "fc metz":                   "metz",
    "angers":                    "angers",
    "sco angers":                "angers",
    "auxerre":                   "auxerre",
    "aj auxerre":                "auxerre",
    "saint-etienne":             "st_etienne",
    "as saint-etienne":          "st_etienne",
    "asse":                      "st_etienne",

    # ── Premier League ──────────────────────────────────────────────────────
    "manchester city":           "man_city",
    "man city":                  "man_city",
    "manchester united":         "man_united",
    "man utd":                   "man_united",
    "manchester utd":            "man_united",
    "arsenal":                   "arsenal",
    "chelsea":                   "chelsea",
    "liverpool":                 "liverpool",
    "tottenham":                 "tottenham",
    "spurs":                     "tottenham",
    "newcastle":                 "newcastle",
    "newcastle united":          "newcastle",
    "aston villa":               "aston_villa",
    "west ham":                  "west_ham",
    "brighton":                  "brighton",
    "fulham":                    "fulham",
    "brentford":                 "brentford",
    "crystal palace":            "crystal_palace",
    "everton":                   "everton",
    "nottingham forest":         "nott'm_forest",
    "wolves":                    "wolves",
    "wolverhampton":             "wolves",
    "bournemouth":               "bournemouth",
    "burnley":                   "burnley",
    "leeds":                     "leeds",
    "leeds united":              "leeds",
    "sunderland":                "sunderland",

    # ── La Liga ─────────────────────────────────────────────────────────────
    "real madrid":               "real_madrid",
    "fc barcelone":              "barcelona",
    "barcelona":                 "barcelona",
    "fc barcelona":              "barcelona",
    "atletico madrid":           "ath_madrid",
    "atletico de madrid":        "ath_madrid",
    "atletico":                  "ath_madrid",
    "séville":                   "sevilla",
    "sevilla":                   "sevilla",
    "real sociedad":             "sociedad",
    "real betis":                "betis",
    "villarreal":                "villarreal",
    "athletic bilbao":           "ath_bilbao",
    "athletic club":             "ath_bilbao",
    "valence":                   "valencia",
    "valencia":                  "valencia",
    "getafe":                    "getafe",
    "osasuna":                   "osasuna",
    "rayo vallecano":            "vallecano",
    "girona":                    "girona",
    "gerone":                    "girona",
    "gérone":                    "girona",
    "alaves":                    "alaves",
    "alavés":                    "alaves",
    "celta vigo":                "celta",
    "espanyol":                  "espanol",
    "majorque":                  "mallorca",
    "mallorca":                  "mallorca",
    "elche":                     "elche",
    "levante":                   "levante",
    "real oviedo":               "oviedo",
    "oviedo":                    "oviedo",

    # ── Serie A ─────────────────────────────────────────────────────────────
    "inter milan":               "inter",
    "inter":                     "inter",
    "ac milan":                  "milan",
    "milan":                     "milan",
    "juventus":                  "juventus",
    "napoli":                    "napoli",
    "as roma":                   "roma",
    "roma":                      "roma",
    "lazio":                     "lazio",
    "atalanta":                  "atalanta",
    "fiorentina":                "fiorentina",
    "torino":                    "torino",
    "bologna":                   "bologna",
    "udinese":                   "udinese",
    "hellas verone":             "verona",
    "verona":                    "verona",
    "cagliari":                  "cagliari",
    "lecce":                     "lecce",
    "sassuolo":                  "sassuolo",
    "genoa":                     "genoa",
    "parme":                     "parma",
    "parma":                     "parma",
    "como":                      "como",
    "cremonese":                 "cremonese",
    "pisa":                      "pisa",

    # ── Bundesliga ──────────────────────────────────────────────────────────
    "bayern munich":             "bayern_munich",
    "fc bayern":                 "bayern_munich",
    "borussia dortmund":         "dortmund",
    "dortmund":                  "dortmund",
    "bayer leverkusen":          "leverkusen",
    "leverkusen":                "leverkusen",
    "rb leipzig":                "rb_leipzig",
    "leipzig":                   "rb_leipzig",
    "eintracht frankfurt":       "ein_frankfurt",
    "francfort":                 "ein_frankfurt",
    "wolfsburg":                 "wolfsburg",
    "vfb stuttgart":             "stuttgart",
    "stuttgart":                 "stuttgart",
    "borussia monchengladbach":  "m'gladbach",
    "borussia mönchengladbach":  "m'gladbach",
    "gladbach":                  "m'gladbach",
    "union berlin":              "union_berlin",
    "werder bremen":             "werder_bremen",
    "bremen":                    "werder_bremen",
    "sc freiburg":               "freiburg",
    "fribourg":                  "freiburg",
    "augsbourg":                 "augsburg",
    "augsburg":                  "augsburg",
    "heidenheim":                "heidenheim",
    "st. pauli":                 "st_pauli",
    "st pauli":                  "st_pauli",
    "fc cologne":                "fc_koln",
    "cologne":                   "fc_koln",
    "fc köln":                   "fc_koln",
    "köln":                      "fc_koln",
    "hambourg":                  "hamburg",
    "hamburg":                   "hamburg",
    "hambourg sv":               "hamburg",
    "hamburger sv":              "hamburg",
    "mayence":                   "mainz",
    "mainz":                     "mainz",
    "hoffenheim":                "hoffenheim",

    # ── Ligue 2 ─────────────────────────────────────────────────────────────
    "amiens":                    "amiens",
    "annecy":                    "annecy",
    "bastia":                    "bastia",
    "boulogne":                  "boulogne",
    "dunkerque":                 "dunkerque",
    "grenoble":                  "grenoble",
    "guingamp":                  "guingamp",
    "laval":                     "laval",
    "le mans":                   "le_mans",
    "nancy":                     "nancy",
    "pau":                       "pau_fc",
    "pau fc":                    "pau_fc",
    "red star":                  "red_star",
    "rodez":                     "rodez",
    "troyes":                    "troyes",
    "estac troyes":              "troyes",
}

# Normalisation noms de joueurs tennis : Betclic → clé Tennis Abstract
PLAYER_MAP: dict[str, str] = {
    "novak djokovic":   "djokovic",
    "djokovic":         "djokovic",
    "carlos alcaraz":   "alcaraz",
    "alcaraz":          "alcaraz",
    "jannik sinner":    "sinner",
    "sinner":           "sinner",
    "daniil medvedev":  "medvedev",
    "medvedev":         "medvedev",
    "alexander zverev": "zverev",
    "zverev":           "zverev",
    "andrey rublev":    "rublev",
    "rublev":           "rublev",
    "casper ruud":      "ruud",
    "ruud":             "ruud",
    "stefanos tsitsipas": "tsitsipas",
    "tsitsipas":        "tsitsipas",
    "taylor fritz":     "fritz",
    "fritz":            "fritz",
    "tommy paul":       "tommy_paul",
    "frances tiafoe":   "tiafoe",
    "tiafoe":           "tiafoe",
    "holger rune":      "rune",
    "rune":             "rune",
    "grigor dimitrov":  "dimitrov",
    "dimitrov":         "dimitrov",
    "hubert hurkacz":   "hurkacz",
    "hurkacz":          "hurkacz",
    "ben shelton":      "shelton",
    "shelton":          "shelton",
    "rafael nadal":     "nadal",
    "nadal":            "nadal",
    "roger federer":    "federer",
    "federer":          "federer",
    "felix auger-aliassime": "auger_aliassime",
    "auger-aliassime":  "auger_aliassime",
    "jack draper":      "draper",
    "draper":           "draper",
    "ugo humbert":      "humbert",
    "humbert":          "humbert",
    "arthur fils":      "fils",
    "fils":             "fils",
    "giovanni mpetshi perricard": "mpetshi_perricard",
    "mpetshi perricard": "mpetshi_perricard",
    # Jodar → probable "Jodar De Jong" ou joueur moins connu, on le gère par fuzzy
}


def _normalize(name: str) -> str:
    """Retire accents, met en minuscule, normalise espaces."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower().strip()
    name = re.sub(r"\s+", " ", name)
    return name


def resolve_team(betclic_name: str, known_params: dict = None) -> tuple[str, str]:
    """
    Retourne (clé_fbref, confidence) depuis le nom Betclic.
    confidence : "high" (trouvé dans dict), "medium" (fuzzy), "low" (non trouvé)

    known_params : dict des paramètres en BDD (clés = "att_xxx", "def_xxx")
                   utilisé pour valider que la clé existe bien en BDD.
    """
    norm = _normalize(betclic_name)

    # 1. Lookup direct
    if norm in TEAM_MAP:
        key = TEAM_MAP[norm]
        if known_params is None or f"att_{key}" in known_params:
            return key, "high"
        return key, "medium"  # clé connue mais pas encore en BDD

    # 2. Lookup avec mots-clés partiels — uniquement si l'alias est suffisamment long
    #    pour éviter "om" ∈ "tomas", "lens" ∈ "valencia", etc.
    for alias, key in TEAM_MAP.items():
        if len(alias) < 5:
            continue
        # Match sur mots entiers (pas substring brute)
        if alias == norm or norm in alias.split() or alias in norm.split():
            if known_params is None or f"att_{key}" in known_params:
                return key, "high"
            return key, "medium"

    # 3. Fuzzy matching strict sur les clés FBref existantes en BDD
    if known_params:
        fbref_teams = [k[4:] for k in known_params if k.startswith("att_")]
        matches = get_close_matches(norm.replace(" ", "_"), fbref_teams, n=1, cutoff=0.85)
        if matches:
            return matches[0], "medium"

    # 4. Fallback : normalisation brute
    key = re.sub(r"[^a-z0-9]", "_", norm).strip("_")
    return key, "low"


def resolve_player(betclic_name: str, known_params: dict = None) -> tuple[str, str]:
    """
    Retourne (clé_tennis_abstract, confidence) depuis le nom Betclic.
    """
    norm = _normalize(betclic_name)

    if norm in PLAYER_MAP:
        key = PLAYER_MAP[norm]
        return key, "high"

    # Lookup partiel (nom de famille)
    parts = norm.split()
    if parts:
        lastname = parts[-1]
        if lastname in PLAYER_MAP:
            return PLAYER_MAP[lastname], "high"
        for alias, key in PLAYER_MAP.items():
            if lastname in alias:
                return key, "medium"

    # Fuzzy
    if known_params:
        tennis_players = [k.split("_hard")[0].split("_clay")[0].split("_grass")[0]
                          for k in known_params if k.startswith("ace_rate_")]
        players_unique = list(set(p[9:] for p in tennis_players if p.startswith("ace_rate_")))
        matches = get_close_matches(norm.replace(" ", "_"), players_unique, n=1, cutoff=0.6)
        if matches:
            return matches[0], "medium"

    key = re.sub(r"[^a-z0-9]", "_", norm).strip("_")
    return key, "low"


def parse_event_name(event_name: str) -> tuple[str, str]:
    """
    Parse "PSG vs Nantes" → ("PSG", "Nantes")
    Gère : " - ", " vs ", " / ", " contre "
    """
    for sep in [" vs ", " - ", " / ", " contre ", " v "]:
        if sep in event_name:
            parts = event_name.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return event_name.strip(), ""

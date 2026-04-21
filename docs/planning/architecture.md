# Architecture Technique — BettingEdge
*Architecte : Winston (BMAD) — 2026-04-22*
*Source : docs/planning/prd-bettingedge.md*

---

## 1. Vue d'ensemble

BettingEdge est une application **monolithique locale** : backend Python + frontend HTML/JS servis depuis le même processus FastAPI. Pas de cloud, pas de microservices. La simplicité est un choix délibéré — un seul utilisateur, un seul poste.

```
┌─────────────────────────────────────────────┐
│                  NAVIGATEUR                  │
│         HTML / CSS / JS vanilla              │
│         Chart.js (courbes perf)              │
└──────────────────┬──────────────────────────┘
                   │ HTTP REST (JSON)
                   │ localhost:8000
┌──────────────────▼──────────────────────────┐
│               FASTAPI (Python)               │
│  /api/strategy-a  /api/strategy-b            │
│  /api/strategy-c  /api/simulation            │
│  /api/learning    /api/dashboard             │
│  StaticFiles → frontend/                     │
└──────┬────────────────────┬─────────────────┘
       │                    │
┌──────▼──────┐    ┌────────▼────────┐
│  MODÈLES    │    │    SCRAPERS     │
│  dixon_coles│    │  betclic.py     │
│  poisson.py │    │  fbref.py       │
│  corners.py │    │  tennis_abs.py  │
└──────┬──────┘    └────────┬────────┘
       │                    │
┌──────▼────────────────────▼─────────────────┐
│              SQLite (local)                  │
│  bets · model_params · odds_history          │
│  niche_performance                           │
└─────────────────────────────────────────────┘
       ▲
┌──────┴──────────────────────────────────────┐
│           SCHEDULER (APScheduler)            │
│  Scraping quotidien 06h00                    │
│  Recalibration Brier Score auto              │
└─────────────────────────────────────────────┘
```

---

## 2. Structure des Dossiers

```
bettingedge/
├── main.py                      # FastAPI app, routes, static files
├── scheduler.py                 # APScheduler — jobs quotidiens
├── requirements.txt
│
├── backend/
│   ├── scrapers/
│   │   ├── betclic.py           # Playwright — cotes + boosts
│   │   ├── fbref.py             # Requests/BS4 — stats foot
│   │   └── tennis_abstract.py   # Requests — stats tennis
│   │
│   ├── models/
│   │   ├── dixon_coles.py       # Modèle buts + correction τ
│   │   ├── poisson.py           # Poisson générique (aces, corners)
│   │   └── markov_tennis.py     # Proba jeux/sets/match
│   │
│   ├── strategies/
│   │   ├── strategy_a.py        # De-vigging + consensus + EV boost
│   │   ├── strategy_b.py        # Value betting niches
│   │   └── strategy_c.py        # CLV tracker
│   │
│   ├── core/
│   │   ├── kelly.py             # Kelly fractionné
│   │   ├── ev.py                # Calcul EV
│   │   ├── devig.py             # De-vigging multiplicatif
│   │   └── risk_factor.py       # RF composite 5 dimensions
│   │
│   ├── learning/
│   │   ├── calibration.py       # Brier Score glissant (fenêtre 50)
│   │   ├── bayesian_update.py   # Mise à jour paramètres
│   │   └── error_explainer.py   # Contribution features à l'erreur
│   │
│   └── db/
│       ├── database.py          # SQLAlchemy engine + session
│       ├── models.py            # ORM — tables SQLite
│       ├── crud.py              # Opérations CRUD
│       └── seed.py              # Paramètres initiaux Dixon-Coles 1997
│
└── frontend/
    ├── index.html               # Dashboard /
    ├── strategy-a.html          # /strategy-a
    ├── strategy-b.html          # /strategy-b
    ├── strategy-c.html          # /strategy-c
    ├── simulation.html          # /simulation
    ├── learning.html            # /learning
    ├── docs.html                # /docs
    ├── css/
    │   └── style.css
    └── js/
        ├── core/
        │   ├── api.js           # fetch() wrapper centralisé
        │   ├── charts.js        # Chart.js wrappers réutilisables
        │   └── tooltips.js      # Système tooltips (?)
        ├── dashboard.js
        ├── strategy-a.js
        ├── strategy-b.js
        ├── strategy-c.js
        ├── simulation.js
        ├── learning.js
        └── docs.js
```

---

## 3. API REST — Contrat

### Routes principales

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/dashboard` | KPIs globaux + courbes 3 portefeuilles |
| GET | `/api/strategy-a/boosts` | Boosts du jour avec EV calculé |
| POST | `/api/strategy-a/calculate` | Calcul EV pour un boost saisi manuellement |
| GET | `/api/strategy-b/bets` | Value bets actifs par niche |
| GET | `/api/strategy-c/clv` | Historique CLV + moyenne |
| GET | `/api/simulation/portfolios` | État des 3 portefeuilles |
| POST | `/api/simulation/record-bet` | Enregistrer un pari pris |
| POST | `/api/simulation/resolve-bet` | Saisir le résultat d'un pari |
| GET | `/api/learning/calibration` | Données courbe de calibration |
| GET | `/api/learning/errors` | Analyse erreurs récentes |
| GET | `/api/learning/niches` | Ranking niches par ROI |
| POST | `/api/learning/recalibrate` | Forcer recalibration |
| GET | `/api/scraper/status` | Statut dernière collecte |
| POST | `/api/scraper/run` | Lancer collecte manuelle |

### Format réponse standard
```json
{
  "status": "ok",
  "data": {},
  "updated_at": "2026-04-22T10:00:00Z"
}
```

---

## 4. Schéma BDD — SQLite

### Table `bets`
```sql
CREATE TABLE bets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy        TEXT NOT NULL,          -- 'A', 'B', 'C'
    market          TEXT NOT NULL,          -- 'boost', 'corners', 'aces', 'clv'...
    sport           TEXT NOT NULL,          -- 'football', 'tennis'
    league          TEXT,
    surface         TEXT,                   -- tennis uniquement
    p_estimated     REAL NOT NULL,          -- prob estimée par notre modèle
    odds_taken      REAL NOT NULL,          -- cote au moment du pari
    odds_close      REAL,                   -- cote de clôture (post-match)
    odds_fair       REAL,                   -- cote juste modélisée
    ev_expected     REAL NOT NULL,
    result          INTEGER,                -- 1=gagné, 0=perdu, NULL=en cours
    ev_realized     REAL,
    stake           REAL NOT NULL,
    portfolio_before REAL NOT NULL,
    portfolio_after  REAL,
    features_json   TEXT,                   -- JSON: λ, ρ, κ, surface, forme...
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);
```

### Table `model_params`
```sql
CREATE TABLE model_params (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,          -- 'dixon_coles', 'poisson_aces'...
    param_name      TEXT NOT NULL,          -- 'att_PSG', 'ace_rate_Djokovic_clay'
    param_value     REAL NOT NULL,
    confidence      REAL DEFAULT 1.0,       -- poids Bayésien
    updated_at      TEXT NOT NULL,
    UNIQUE(model_name, param_name)
);
```

### Table `odds_history`
```sql
CREATE TABLE odds_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,
    market          TEXT NOT NULL,
    bookmaker       TEXT DEFAULT 'betclic',
    odds            REAL NOT NULL,
    recorded_at     TEXT NOT NULL
);
```

### Table `niche_performance`
```sql
CREATE TABLE niche_performance (
    niche           TEXT PRIMARY KEY,       -- 'corners_ligue1', 'aces_atp_clay'
    n_bets          INTEGER DEFAULT 0,
    roi             REAL DEFAULT 0.0,
    clv_mean        REAL DEFAULT 0.0,
    brier_score     REAL DEFAULT 0.25,      -- init neutre
    last_updated    TEXT NOT NULL
);
```

### Table `portfolios`
```sql
CREATE TABLE portfolios (
    strategy        TEXT PRIMARY KEY,       -- 'A', 'B', 'C'
    capital_initial REAL NOT NULL,
    capital_current REAL NOT NULL,
    n_bets          INTEGER DEFAULT 0,
    updated_at      TEXT NOT NULL
);
```

---

## 5. Modules Clés — Interfaces

### `core/risk_factor.py`
```python
def compute_rf(
    n_similaires: int,
    ev: float,
    p_estimated: float,
    odds: float,
    brier_score: float,
    clv_mean: float
) -> float:
    """Retourne RF ∈ [0, 1]"""
```

### `core/kelly.py`
```python
def kelly_fraction(p: float, odds: float, kappa: float = 0.25) -> float:
    """f* = Kelly × κ, toujours ≤ 0.05 du portefeuille"""

def recommended_stake(
    portfolio: float, kelly_f: float, rf: float, max_pct: float = 0.05
) -> float:
    """mise = min(f* × RF × portfolio, max_pct × portfolio)"""
```

### `models/dixon_coles.py`
```python
def fit(match_history: pd.DataFrame) -> dict:
    """Retourne {att_i, def_i, γ, ρ} via MLE"""

def predict(home: str, away: str, params: dict) -> np.ndarray:
    """Matrice 10×10 de probabilités de scores"""

def prob_btts(matrix: np.ndarray) -> float: ...
def prob_over(matrix: np.ndarray, threshold: float = 2.5) -> float: ...
```

### `learning/calibration.py`
```python
def brier_score_rolling(bets: list[dict], window: int = 50) -> float:
    """BS glissant sur les N derniers paris résolus"""

def calibration_curve(bets: list[dict], n_bins: int = 10) -> dict:
    """Pour la courbe de calibration frontend"""
```

---

## 6. Scraping — Stratégie Anti-Ban

### Betclic (Playwright)
- Délai aléatoire entre chaque requête : `random.uniform(3, 8)` secondes
- User-agent rotatif (liste de 5 UAs desktop courants)
- Session Playwright persistante (cookies) — pas de re-login à chaque scrape
- Fallback : saisie manuelle via `/api/strategy-a/calculate` si scraper bloqué
- Fréquence : 1× par jour à 06h00 (APScheduler)

### FBref / Tennis Abstract (Requests + BeautifulSoup)
- Pas de JavaScript requis → requests simple
- Cache local 24h : si données < 24h, pas de re-scrape
- Headers : `User-Agent` desktop standard, `Referer` correct

---

## 7. Scheduler (APScheduler)

```python
# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(scrape_betclic,        'cron', hour=6, minute=0)
scheduler.add_job(scrape_fbref,          'cron', hour=6, minute=10)
scheduler.add_job(scrape_tennis_abstract,'cron', hour=6, minute=20)
scheduler.add_job(recalibrate_models,    'cron', hour=6, minute=30)
```

Le scheduler démarre avec FastAPI (`lifespan`) et s'arrête proprement à la fermeture.

---

## 8. Frontend — Principes

- **Pas de framework** : HTML/CSS/JS vanilla uniquement
- **Pas de build step** : fichiers servis directement par FastAPI `StaticFiles`
- **api.js** : wrapper `fetch()` centralisé — toutes les pages passent par lui
- **charts.js** : wrappers Chart.js réutilisables (courbe perf, calibration, heatmap)
- **tooltips.js** : système `(?)` unifié — hover → popup → lien vers `/docs#ancre`
- Chaque page est **indépendante** : son propre `.js`, aucune dépendance inter-pages

### Comparaison des stratégies (Dashboard)
```javascript
// Un seul appel, 3 datasets superposés
Chart.js LineChart({
  datasets: [portfolioA, portfolioB, portfolioC],
  xAxis: 'date',
  yAxis: 'capital (€ ou %)'
})
```

---

## 9. Démarrage de l'Application

```bash
# Installation
pip install -r requirements.txt
playwright install chromium

# Initialisation BDD
python -m backend.db.seed

# Lancement
uvicorn main:app --reload --port 8000

# Accès
http://localhost:8000
```

---

## 10. Décisions Architecturales & Raisons

| Décision | Raison |
|----------|--------|
| Monolithe local (pas de cloud) | Budget 0€, un seul utilisateur, latence nulle |
| SQLite (pas Postgres) | Pas de serveur à maintenir, fichier unique sauvegardable |
| FastAPI sert le frontend | Évite CORS, un seul processus, démarrage simple |
| APScheduler intégré | Pas de Celery/Redis — overkill pour 1 tâche/jour |
| Playwright (pas Selenium) | API async, plus rapide, meilleur support JS moderne |
| Stratégies isolées dans le code | Modifier B ne risque jamais de casser A ou C |
| Kelly × 0.25 hardcodé | Protection contre ruine, pas de paramètre exposé à l'UI |
| Pas de React/Vue | Pas de npm, pas de build, chargement instantané |

---

## 11. Risques Techniques & Mitigations

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Playwright bloqué par Betclic | Élevé | Fallback saisie manuelle + délais aléatoires |
| Dixon-Coles mal calibré au démarrage | Moyen | Seed avec paramètres Dixon-Coles 1997 (paper) |
| SQLite corrompu | Faible | Backup automatique du fichier `.db` avant chaque scrape |
| Port 8000 occupé | Faible | Configurable via `.env` |
| Drift du modèle non détecté | Moyen | Alerte Brier Score > 0.22 affichée sur dashboard |

---

## 12. Prochaine Étape

Passer à **Bob (SM)** pour découper en **Epics et Stories** prêtes pour le dev.

Ordre recommandé des Epics :
1. **Epic 0** — Setup projet (structure, BDD, FastAPI base)
2. **Epic 1** — Scraper Betclic + FBref + Tennis Abstract
3. **Epic 2** — Moteur de modèles (Dixon-Coles, Poisson, Markov)
4. **Epic 3** — Stratégie A (Boosts EV)
5. **Epic 4** — Stratégie B (Value betting niches)
6. **Epic 5** — Stratégie C (CLV tracker)
7. **Epic 6** — Dashboard + comparaison portefeuilles
8. **Epic 7** — Moteur d'apprentissage
9. **Epic 8** — Page Documentation + tooltips

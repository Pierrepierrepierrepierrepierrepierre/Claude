# PRD — BettingEdge
*Product Manager : John (BMAD) — 2026-04-21*
*Brief source : docs/planning/brief-analyst-betting.md*

---

## 1. Vision Produit

**Pour** Pierre, data engineer qui parie sur Betclic (foot + tennis),
**qui veut** maximiser son espérance de gain sur 3 mois avec un risque de ban minimal,
**BettingEdge est** une application web d'analyse et de recommandation de paris,
**qui** modélise la probabilité réelle des événements, détecte les cotes sous-évaluées, et apprend de chaque résultat pour affiner ses modèles en continu.

---

## 2. Objectif Métier (3 mois)

| Métrique | Cible |
|----------|-------|
| ROI moyen portefeuille | > 5% (après vig) |
| CLV moyen | > 2% sur marchés principaux |
| Brier Score | < 0.20 sur chaque modèle actif |
| Drawdown max par stratégie | < 20% du portefeuille de la stratégie |
| Risque de ban Betclic | Aucun compte limité en v1 |

---

## 3. Stack Technique

| Couche | Technologie |
|--------|-------------|
| Backend calculs | Python 3.11+ — FastAPI |
| Modèles | numpy, scipy, pandas |
| Scraping | Playwright ou Selenium (Betclic) + FBref/Tennis Abstract |
| Stockage | SQLite (local) via SQLAlchemy |
| Frontend | HTML/CSS/JS vanilla + Chart.js (dashboards) |
| Communication | REST API JSON entre backend et frontend |
| Déploiement | Local (localhost) — pas de cloud en v1 |

---

## 4. Utilisateurs & Contexte

- **Utilisateur unique** : Pierre
- **Usage** : avant chaque journée de paris (matin ou veille), plus consultation post-résultats
- **Devices** : desktop uniquement
- **Niveau** : expert en data, débutant en capital de paris

---

## 5. Features — Priorisées MoSCoW

### MUST (v1 — bloquant pour l'objectif 3 mois)

**M1 — Scraper de données**
- Scraping automatique : stats foot (FBref/Understat), stats tennis (Tennis Abstract)
- Scraping cotes Betclic : marchés principaux + secondaires + boosts du jour
- Stockage en base SQLite avec horodatage
- Scheduler : mise à jour quotidienne automatique

**M2 — Moteur de modèles mathématiques**
- Stratégie A : de-vigging + consensus multi-marchés + calcul EV boost
- Stratégie B : Dixon-Coles foot (buts, BTTS, Over/Under, corners, cartons/arbitre) + Poisson tennis (double fautes, tie-breaks)
- Stratégie C : tracking cotes d'ouverture → clôture, calcul CLV
- Facteur Risque composite (5 dimensions) par pari

**M3 — Recommandations de paris**
- Liste de paris EV+ du jour par stratégie
- Mise recommandée (Kelly fractionné × RF)
- Affichage : EV, facteur risque, cote juste vs cote Betclic, mise conseillée

**M4 — Portefeuilles simulés**
- 3 portefeuilles séparés (un par stratégie), capital fictif configurable
- Enregistrement de chaque pari pris (simulé ou réel)
- Saisie du résultat après le match

**M5 — Moteur d'apprentissage**
- Brier Score glissant par modèle (fenêtre 50 paris)
- Mise à jour Bayésienne des paramètres après chaque résultat
- Analyse "pourquoi j'ai perdu" par contribution de feature
- Détection de niche dégradée (EV réalisé < 50% EV espéré sur 30 paris)

**M6 — Dashboard principal**
- Courbes de performance des 3 portefeuilles (Chart.js)
- KPIs en temps réel : ROI, CLV moyen, % EV+, drawdown max
- Comparaison croisée des stratégies

---

### SHOULD (v1 si temps, sinon v1.1)

**S1 — Page Apprentissage**
- Courbe de calibration (p_estimée vs fréquence réelle)
- Heatmap performances par niche × sport × surface
- Ranking des niches par ROI 30 derniers paris
- Bouton "Forcer recalibration"

**S2 — Documentation encyclopédique**
- 9 sections : concepts fondamentaux, 3 stratégies, modèles maths, gestion capital, facteur risque, CLV, apprentissage, glossaire, ressources
- Tooltips (?) partout dans l'app → lien ancré vers section doc

**S3 — Export données**
- Export CSV/JSON de l'historique des paris pour analyse Python externe

**S4 — Alertes CLV**
- Notification quand une cote Betclic est en train de baisser (mouvement détecté)

---

### COULD (v2)

**C1 — Multi-bookmakers** (débloquer l'arbitrage inter-bookmakers)
**C2 — Poker en ligne** (scope séparé, post v1)
**C3 — Paris live / in-play**
**C4 — Interface mobile**
**C5 — Déploiement cloud** (accès hors domicile)

### WON'T (v1)

- Connexion API officielle Betclic (inexistante publiquement)
- Trading automatique (Pierre décide toujours manuellement)
- Partage/monétisation de l'outil

---

## 6. Architecture des Pages

| Page | Route | Contenu |
|------|-------|---------|
| Dashboard | `/` | KPIs globaux, courbes 3 portefeuilles, paris du jour |
| Stratégie A | `/strategy-a` | Boosts du jour, EV calculator, historique |
| Stratégie B | `/strategy-b` | Value bets par niche, filtres sport/marché |
| Stratégie C | `/strategy-c` | Tracker CLV, alertes mouvement de cotes |
| Simulation | `/simulation` | Portefeuilles fictifs, saisie résultats |
| Apprentissage | `/learning` | Calibration, erreurs, ranking niches |
| Documentation | `/docs` | Guide complet + glossaire interactif |

---

## 7. Architecture Technique Cible

```
bettingedge/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── scrapers/
│   │   ├── betclic.py           # Cotes + boosts Betclic
│   │   ├── fbref.py             # Stats foot
│   │   └── tennis_abstract.py  # Stats tennis
│   ├── models/
│   │   ├── dixon_coles.py       # Modèle buts foot
│   │   ├── poisson.py           # Modèle tennis (double fautes, tie-breaks)
│   │   └── corners.py           # Modèle corners
│   ├── strategies/
│   │   ├── strategy_a.py        # De-vigging + EV boost
│   │   ├── strategy_b.py        # Value betting niches
│   │   └── strategy_c.py        # CLV tracker
│   ├── core/
│   │   ├── kelly.py             # Kelly fractionné
│   │   ├── ev.py                # Calcul EV
│   │   └── risk_factor.py       # Facteur risque composite
│   ├── learning/
│   │   ├── calibration.py       # Brier score glissant
│   │   ├── bayesian_update.py   # Mise à jour paramètres
│   │   └── error_explainer.py   # Analyse erreurs
│   └── db/
│       ├── models.py            # Schéma SQLite (SQLAlchemy)
│       └── seed.py              # Données initiales
├── frontend/
│   ├── index.html               # Dashboard
│   ├── css/style.css
│   └── js/
│       ├── dashboard.js
│       ├── strategy-a.js
│       ├── strategy-b.js
│       ├── strategy-c.js
│       ├── simulation.js
│       ├── learning.js
│       ├── docs.js
│       └── charts.js            # Chart.js wrappers
└── scheduler.py                 # Cron scraping quotidien
```

---

## 8. Schéma de Données (SQLite)

### Table `bets`
```sql
id, strategy, market, sport, league, surface,
p_estimated, odds_taken, odds_close, odds_betclic_fair,
ev_expected, result, ev_realized,
stake, portfolio_before, portfolio_after,
features_json,  -- λ, ρ, κ, arbitre, forme, h2h...
created_at, resolved_at
```

### Table `model_params`
```sql
model_name, param_name, param_value, confidence, updated_at
```

### Table `odds_history`
```sql
event_id, market, bookmaker, odds, recorded_at
```

### Table `niche_performance`
```sql
niche, n_bets, roi, clv_mean, brier_score, last_updated
```

---

## 9. Critères d'Acceptance (Definition of Done)

| Feature | Critère |
|---------|---------|
| Scraper | Données fraîches < 24h en base, zéro erreur sur 7 jours consécutifs |
| Modèle Dixon-Coles | Brier Score < 0.22 sur 50 matchs de validation historique |
| Modèle Poisson tennis | Brier Score < 0.22 sur 50 matchs de validation |
| Stratégie A | EV calculé en < 1s après saisie d'un boost |
| Stratégie B | ≥ 3 niches actives produisant des signaux quotidiens |
| Stratégie C | CLV enregistré sur 100% des paris tracés |
| Facteur Risque | Score affiché sur chaque recommandation, cohérent avec les résultats observés |
| Dashboard | Courbes à jour en < 2s après chargement |
| Apprentissage | Brier Score recalculé automatiquement après chaque résultat saisi |
| Anti-ban | Aucun pattern détectable : délais aléatoires scraping, mises variées |

---

## 10. Risques & Mitigations

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Betclic bloque le scraper | Élevé | User-agent rotatif, délais aléatoires, fallback saisie manuelle |
| Données FBref insuffisantes pour les ligues exotiques | Moyen | Périmètre v1 limité aux top 5 ligues + Ligue 2 |
| Modèle sous-calibré au démarrage (peu de données) | Moyen | Démarrer avec paramètres issus de la littérature académique (Dixon-Coles 1997) |
| Variance court terme décourageante | Faible | Dashboard affiche CLV (indicateur prospectif) en priorité sur P&L brut |

---

## 11. Prochaine Étape

Passer à **Winston (Architecte)** pour valider les choix techniques et produire le document d'architecture, puis **Bob (SM)** pour découper en Epics et Stories.

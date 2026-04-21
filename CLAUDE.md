# BettingEdge — Contexte Projet

> **INSTRUCTION CLAUDE** : Ce fichier est la seule source de vérité du projet. À chaque session, tu dois :
> 1. Lire ce fichier en entier au démarrage
> 2. **Pierre travaille par plan d'action** — mettre à jour `ÉTAT ACTUEL` après chaque plan d'action complété (pas seulement en fin de session)
> 3. Ne jamais laisser un plan d'action se terminer sans avoir mis à jour cette section
> 4. Format de reprise : "reprend au point X" → lire ÉTAT ACTUEL et continuer exactement là

---

## ÉTAT ACTUEL — mis à jour le 2026-04-22

**Phase BMAD :** Architecture validée — en attente de Bob (SM) pour le découpage Epics/Stories

**Dernières décisions prises :**
- CLAUDE.md = source de vérité unique, GitHub = repo `Claude` connecté via SSH
- Travail par plan d'action, ÉTAT ACTUEL mis à jour après chaque plan
- Stack validée : FastAPI + SQLite + HTML/JS vanilla + Chart.js
- Portefeuilles : 3 isolés, capital fictif configurable, pas de transfert inter-stratégies
- Architecture monolithique locale (pas de cloud, pas de microservices)
- FastAPI sert aussi le frontend (StaticFiles) — un seul processus
- Scheduler : APScheduler intégré (pas Celery), scraping 06h00 quotidien
- Playwright pour Betclic (async, JS), Requests+BS4 pour FBref/Tennis Abstract
- Stratégies A/B/C = modules totalement isolés dans le code

**Document d'architecture :** `docs/planning/architecture.md` ✅

**Prochaine étape :** Bob (SM) → découpage en Epics/Stories

**Ordre des Epics prévu :**
1. Epic 0 — Setup projet (structure, BDD, FastAPI base)
2. Epic 1 — Scrapers (Betclic, FBref, Tennis Abstract)
3. Epic 2 — Modèles (Dixon-Coles, Poisson, Markov)
4. Epic 3 — Stratégie A (Boosts EV)
5. Epic 4 — Stratégie B (Value betting niches)
6. Epic 5 — Stratégie C (CLV tracker)
7. Epic 6 — Dashboard + comparaison portefeuilles
8. Epic 7 — Moteur d'apprentissage
9. Epic 8 — Documentation + tooltips

**Ce qui n'est PAS encore fait :**
- Découpage Epics/Stories (Bob, SM)
- Aucune ligne de code écrite

---

Application web personnelle d'aide à la décision pour les paris sportifs. Utilisateur unique : Pierre (data engineer, expert modélisation, débutant capital).

**Bookmaker** : Betclic uniquement. **Sports** : Football + Tennis.

---

## Objectif (3 mois)

| Métrique | Cible |
|----------|-------|
| ROI moyen portefeuille | > 5% (après vig) |
| CLV moyen | > 2% sur marchés principaux |
| Brier Score | < 0.20 par modèle actif |
| Drawdown max par stratégie | < 20% du portefeuille |
| Risque de ban Betclic | Aucun compte limité en v1 |

---

## Stack Technique

| Couche | Techno |
|--------|--------|
| Backend | Python 3.11+, FastAPI |
| Modèles | numpy, scipy, pandas |
| Scraping | Playwright/Selenium (Betclic) + FBref/Tennis Abstract |
| BDD | SQLite local via SQLAlchemy |
| Frontend | HTML/CSS/JS vanilla + Chart.js |
| Déploiement | localhost uniquement (v1) |

---

## Les 3 Stratégies

### Stratégie A — Boosts EV
Détecter les Super Boosts Betclic avec EV positif via de-vigging + consensus multi-marchés.
- `EV_boost = p_consensus × cote_boostée - 1`
- Mise : `f* = Kelly × κ`, κ ∈ [0.1, 0.33], défaut 0.25
- Risque ban : très faible (promos officielles)

### Stratégie B — Value Betting marchés secondaires
Marchés peu couverts par les algos bookmaker : corners, BTTS, cartons, aces, double fautes, tie-breaks.
- Foot : modèle Dixon-Coles (buts, BTTS, Over/Under) + Poisson corners
- Tennis : modèle Poisson aces + Markov sets/jeux
- `value = cote_betclic / cote_juste - 1`

### Stratégie C — Closing Line Value (CLV)
Tracker les cotes prise vs clôture comme KPI de santé du modèle.
- `CLV = cote_pari / cote_clôture - 1`
- CLV > 0 sur durée = edge prouvé
- Risque ban : modéré sur marchés principaux

---

## Modèles Mathématiques Clés

**Dixon-Coles (foot) :**
```
λ_home = att_home × def_away × γ_home   (γ ≈ 1.15–1.25)
λ_away = att_away × def_home
Correction scores bas : τ(0,0), τ(1,0), τ(0,1), τ(1,1) avec paramètre ρ
```

**Poisson Tennis (aces) :**
```
λ_total = λ_A + λ_B
λ_serveur = ace_rate(surface) × E[jeux_service]
P(aces > N) = 1 - CDF_Poisson(N, λ_total)
```

**Facteur Risque composite (5 dimensions) :**
```
F_modèle   = 1 - exp(-N_similaires / 50)
F_ev       = min(1, EV/0.15) × (1 - max(0,(EV-0.15)/0.35))
F_variance = 1 / (1 + p×(1-p)×cote²)
F_calib    = 1 - brier_score/0.25
F_clv      = sigmoid(CLV_moyen × 20)
RF = 0.30×F_modèle + 0.20×F_ev + 0.15×F_variance + 0.20×F_calib + 0.15×F_clv
mise = min(f_kelly × κ × RF × portefeuille, 0.05 × portefeuille)
```

---

## Architecture Fichiers

```
bettingedge/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── scrapers/                # betclic.py, fbref.py, tennis_abstract.py
│   ├── models/                  # dixon_coles.py, poisson.py, corners.py
│   ├── strategies/              # strategy_a.py, strategy_b.py, strategy_c.py
│   ├── core/                    # kelly.py, ev.py, risk_factor.py
│   ├── learning/                # calibration.py, bayesian_update.py, error_explainer.py
│   └── db/                      # models.py (SQLAlchemy), seed.py
├── frontend/
│   ├── index.html               # Dashboard /
│   ├── css/style.css
│   └── js/                      # dashboard.js, strategy-a/b/c.js, simulation.js, learning.js, charts.js
└── scheduler.py                 # Cron scraping quotidien
```

**Pages :** `/` Dashboard · `/strategy-a` · `/strategy-b` · `/strategy-c` · `/simulation` · `/learning` · `/docs`

---

## Portefeuilles de Simulation & Outils de Comparaison

**Philosophie centrale** : Pierre veut tester plusieurs stratégies en parallèle sur une période (ex: 3 jours) et voir laquelle performe le mieux — comme un A/B test de ses propres systèmes.

### 3 Portefeuilles isolés
Chaque stratégie a son propre capital fictif configurable, **totalement séparé** des autres :
- Pas de transfert de capital entre stratégies
- Chaque pari enregistré appartient à un seul portefeuille
- Performance évaluable indépendamment (ex: "Stratégie B a rapporté 8% sur 3 jours, Stratégie A 2%")

### Ce qu'on voit sur chaque cote proposée
Pour chaque recommandation, l'app affiche :
- **Facteur Risque** (RF ∈ [0,1]) — calcul composite 5 dimensions (voir formule)
- **EV attendu** — espérance de gain en %
- **Cote juste** modélisée vs cote Betclic
- **Mise recommandée** — Kelly fractionné × RF × portefeuille de la stratégie
- Détail du calcul visible (transparence totale)

### Outils de comparaison des stratégies (Dashboard)
- **Courbes de performance superposées** des 3 portefeuilles (Chart.js, même axe temporel)
- **Vue comparative côte à côte** : ROI, CLV moyen, % EV+, drawdown max, Brier Score par stratégie
- **Période configurable** : filtrer sur N derniers jours / N derniers paris
- **Ranking automatique** : quelle stratégie est en tête sur la période sélectionnée
- Objectif : permettre à Pierre de décider où concentrer ses mises réelles quand il passera en live

### Isolation du code — règle absolue
Les 3 stratégies sont **totalement indépendantes dans le code**. Modifier Stratégie B ne doit jamais risquer de casser A ou C. Chaque stratégie = module autonome avec son propre state, ses propres paramètres, son propre portefeuille.

---

## BDD SQLite — Tables Principales

- `bets` : id, strategy, market, sport, p_estimated, odds_taken, odds_close, ev_expected, result, ev_realized, stake, features_json, created_at, resolved_at
- `model_params` : model_name, param_name, param_value, confidence, updated_at
- `odds_history` : event_id, market, bookmaker, odds, recorded_at
- `niche_performance` : niche, n_bets, roi, clv_mean, brier_score, last_updated

---

## Moteur d'Apprentissage

Après chaque pari résolu :
1. **Brier Score glissant** (fenêtre 50 paris) → alerte si dérive
2. **Mise à jour Bayésienne** des paramètres (ace_rate, att_i, def_i...) avec pondération récence
3. **Analyse "pourquoi j'ai perdu"** : contribution par feature via dérivée partielle
4. **Détection niche dégradée** : si EV_réalisé < EV_espéré × 0.5 sur ≥ 30 paris

---

## Règles de Développement

- Budget infra : 0 € (tout en local)
- Anti-ban : délais aléatoires scraping, mises variées, pas de pattern détectable
- Portefeuilles isolés par stratégie, pas de transfert inter-stratégies
- Kelly fractionné obligatoire (jamais Kelly plein), plafond 5% par pari
- Phase actuelle : **développement v1** (pas encore de capital réel engagé)
- Framework : BMAD — modulaire, documenté, testé. Pas de vibe coding.
- **Amélioration mathématique proactive** : dès que Pierre partage des résultats de test (même 3 jours), proposer immédiatement des recalibrages concrets (κ, seuils EV, poids RF, λ, ρ...) sans attendre qu'il le demande. Toujours justifier mathématiquement.
- Pierre met un point d'honneur à affiner les modèles en continu — les retours terrain sont la matière première.

---

## Phase Actuelle & Prochaines Étapes

Le PRD est validé (`docs/planning/prd-bettingedge.md`).
Prochaine étape BMAD : **Winston (Architecte)** → document d'architecture technique, puis **Bob (SM)** → découpage Epics/Stories.

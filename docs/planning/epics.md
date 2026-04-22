# Epics & Stories — BettingEdge
*Scrum Master : Bob (BMAD) — 2026-04-22*
*Sources : prd-bettingedge.md · architecture.md*

---

## Légende
- **Points** : 1=trivial · 2=simple · 3=moyen · 5=complexe · 8=très complexe
- **CA** : Critères d'Acceptation

---

## Epic 0 — Setup Projet

**Objectif** : Squelette fonctionnel, BDD initialisée, FastAPI qui répond, app démarrable en une commande.

---

### Story 0.1 — Structure des dossiers
**Points : 1**

Créer l'arborescence complète définie dans architecture.md (dossiers vides + fichiers `__init__.py`).

**CA :**
- [ ] `bettingedge/` contient tous les dossiers définis dans architecture.md
- [ ] `requirements.txt` liste toutes les dépendances (fastapi, uvicorn, sqlalchemy, playwright, apscheduler, requests, beautifulsoup4, numpy, scipy, pandas, pydantic)
- [ ] `pip install -r requirements.txt` s'exécute sans erreur

---

### Story 0.2 — Configuration & variables d'environnement
**Points : 2**

Créer `config.py` avec toutes les constantes configurables via `.env`.

**CA :**
- [ ] `.env.example` documente toutes les variables : `PORT`, `DB_PATH`, `LOG_LEVEL`, `SCRAPE_WINDOW_MIN` (défaut -15), `SCRAPE_WINDOW_MAX` (défaut 30), `KELLY_KAPPA` (défaut 0.25), `MAX_STAKE_PCT` (défaut 0.05)
- [ ] `.env` est dans `.gitignore`
- [ ] `config.py` lit le `.env` via `python-dotenv`

---

### Story 0.3 — Base de données SQLite + migrations
**Points : 3**

Créer `backend/db/database.py`, `models.py`, `crud.py` et `seed.py`.

**CA :**
- [ ] `python -m backend.db.seed` crée le fichier `bettingedge.db` avec les 6 tables (bets, model_params, odds_history, niche_performance, portfolios, scraper_logs)
- [ ] Index `idx_odds_event` créé sur `odds_history`
- [ ] Les 3 portefeuilles (A, B, C) sont initialisés avec `capital_initial` configurable (défaut 1000€)
- [ ] `crud.py` expose : `create_bet`, `resolve_bet`, `get_bets`, `get_portfolio`, `log_scraper`

---

### Story 0.4 — FastAPI app de base + StaticFiles
**Points : 2**

Créer `main.py` avec FastAPI, montage des StaticFiles et route health-check.

**CA :**
- [ ] `uvicorn main:app --port 8000` démarre sans erreur
- [ ] `GET /api/health` retourne `{"status": "ok", "db": "connected"}`
- [ ] `GET /` sert `frontend/index.html`
- [ ] Les fichiers CSS/JS de `frontend/` sont accessibles via le navigateur

---

### Story 0.5 — Backup SQLite automatique
**Points : 2**

Créer `backend/db/backup.py` appelé avant chaque scraping.

**CA :**
- [ ] `backup.py` copie `bettingedge.db` vers `bettingedge_YYYYMMDD_HHMMSS.db` dans un dossier `backups/`
- [ ] `backups/` est dans `.gitignore`
- [ ] Conserve les 7 derniers backups (supprime les plus anciens)
- [ ] Si `bettingedge.db` n'existe pas, ne plante pas

---

**Epic 0 — Total : 10 points**

---

## Epic 1 — Scrapers

**Objectif** : Données fraîches en base chaque matin — cotes Betclic, stats foot, stats tennis. Bootstrap Dixon-Coles obligatoire avant tout pari.

---

### Story 1.1 — Scraper FBref (stats foot)
**Points : 5**

Scraper les stats des top 5 ligues + Ligue 2 depuis FBref : attaque, défense, forme récente par équipe.

**CA :**
- [ ] Scrape les ligues : Ligue 1, Premier League, Liga, Serie A, Bundesliga, Ligue 2
- [ ] Pour chaque équipe : buts marqués/concédés domicile/extérieur (saison courante)
- [ ] Données stockées dans `model_params` : `att_{equipe}`, `def_{equipe}` par ligue
- [ ] Cache 24h : si données < 24h en base, pas de re-scrape
- [ ] Log `scraper_logs` : status `ok` ou `error` + message
- [ ] `python -m backend.scrapers.fbref --bootstrap` calibre Dixon-Coles sur saison courante

---

### Story 1.2 — Scraper Tennis Abstract (stats tennis)
**Points : 3**

Scraper les ace rates et double fautes par joueur ATP/WTA par surface.

**CA :**
- [ ] Pour chaque joueur top 50 ATP : `ace_rate_{joueur}_{surface}` (clay/hard/grass)
- [ ] Double faute rate par joueur + surface
- [ ] Stocké dans `model_params`
- [ ] Cache 24h
- [ ] Log `scraper_logs`

---

### Story 1.3 — Scraper Betclic (cotes + boosts)
**Points : 8**

Scraper les cotes foot/tennis et les Super Boosts du jour via Playwright headed.

**CA :**
- [ ] Mode headed (navigateur visible, non headless)
- [ ] Heure de lancement aléatoire dans fenêtre configurable (défaut 05h45–06h30)
- [ ] Délai aléatoire entre actions : `random.uniform(3, 8)` secondes
- [ ] User-agent rotatif parmi 5 UAs desktop
- [ ] Session persistante (cookies sauvegardés dans `betclic_session.json`)
- [ ] Détection CAPTCHA : si présent → status `captcha` dans `scraper_logs` + arrêt propre
- [ ] Cotes scrappées stockées dans `odds_history` avec `recorded_at`
- [ ] Boosts du jour stockés avec flag `is_boost=True`
- [ ] Log `scraper_logs` systématique
- [ ] Dashboard affiche alerte rouge si dernière entrée Betclic != `ok`

---

### Story 1.4 — Scheduler APScheduler
**Points : 3**

Intégrer APScheduler dans FastAPI avec lifespan, jobs quotidiens ordonnés.

**CA :**
- [ ] Scheduler démarre avec `uvicorn main:app --port 8000` (sans `--reload`)
- [ ] Jobs : backup (05h40 aléatoire) → fbref (06h00±) → tennis_abstract (06h10±) → betclic (06h20±) → recalibration (06h40±)
- [ ] Scheduler s'arrête proprement à la fermeture de l'app
- [ ] `GET /api/scraper/status` retourne le statut des derniers runs
- [ ] `POST /api/scraper/run` déclenche un run manuel (utile si scrape raté)

---

**Epic 1 — Total : 19 points**

---

## Epic 2 — Moteur de Modèles

**Objectif** : Modèles mathématiques calibrés produisant des probabilités fiables (Brier Score < 0.22 sur validation historique).

---

### Story 2.1 — Dixon-Coles (modèle buts foot)
**Points : 8**

Implémenter le modèle Dixon-Coles complet avec correction τ pour les faibles scores.

**CA :**
- [ ] `fit(match_history)` calibre `att_i`, `def_i`, `γ`, `ρ` via MLE (scipy.optimize)
- [ ] `predict(home, away, params)` retourne matrice 10×10 de probabilités de scores
- [ ] `prob_btts(matrix)` → P(les deux équipes marquent)
- [ ] `prob_over(matrix, threshold)` → P(buts > N)
- [ ] Correction τ appliquée pour scores (0,0), (1,0), (0,1), (1,1)
- [ ] Brier Score < 0.22 sur 50 matchs de validation historique FBref
- [ ] Paramètres sauvegardés/chargés depuis `model_params`

---

### Story 2.2 — Modèle Poisson générique (aces, corners)
**Points : 5**

Implémenter `poisson.py` générique utilisable pour aces tennis et corners foot.

**CA :**
- [ ] `predict_over(lambda_total, threshold)` → P(événements > N)
- [ ] `predict_exact(lambda_total, k)` → P(exactement k événements)
- [ ] Pour aces : `lambda = ace_rate(surface) × E[jeux_service]`
- [ ] Pour corners : `lambda_home = moy_corners × (1 + α × diff_xG)`
- [ ] Brier Score < 0.22 sur 50 matchs de validation

---

### Story 2.3 — Modèle Markov tennis (jeux/sets/match)
**Points : 5**

Calculer les probabilités de jeux, sets et match depuis les probabilités de point.

**CA :**
- [ ] `prob_game(p_server)` → probabilité de gagner un jeu au service
- [ ] `prob_set(p_hold_a, p_hold_b)` → probabilité de gagner un set
- [ ] `prob_match(p_hold_a, p_hold_b, format)` → format BO3 ou BO5
- [ ] `E_jeux_service(p_hold_a, p_hold_b)` → nombre attendu de jeux de service (pour Poisson aces)
- [ ] Résultats cohérents avec les données historiques Tennis Abstract

---

### Story 2.4 — Core : EV, De-vigging, Kelly, Facteur Risque
**Points : 5**

Implémenter les 4 modules `core/` partagés par toutes les stratégies.

**CA :**
- [ ] `devig.py` : méthode multiplicative → `p_normalisée = p_implicite / Σ p_implicites`
- [ ] `ev.py` : `EV = p_estimée × cote - 1`
- [ ] `kelly.py` : `f* = Kelly × κ`, plafond `max_pct × portfolio`
- [ ] `risk_factor.py` : RF composite 5 dimensions (F_modèle, F_ev, F_variance, F_calib, F_clv) → RF ∈ [0,1]
- [ ] Tests unitaires sur cas connus (EV=0 si p=1/cote, Kelly=0 si EV≤0)

---

**Epic 2 — Total : 23 points**

---

## Epic 3 — Stratégie A (Boosts EV)

**Objectif** : Détecter et afficher les Super Boosts Betclic avec EV positif, mise recommandée calculée.

---

### Story 3.1 — Backend Stratégie A
**Points : 3**

`strategy_a.py` : calcul EV boost via de-vigging + consensus multi-marchés.

**CA :**
- [ ] `calculate_boost_ev(boost_odds, market_odds_dict)` → `{p_consensus, ev, is_positive}`
- [ ] Consensus pondéré : `p_consensus = moyenne_pondérée(p_1X2, p_AH, p_OU)`
- [ ] Seuil configurable (défaut EV > 3% pour absorber erreur d'estimation)
- [ ] `GET /api/strategy-a/boosts` retourne boosts du jour filtrés EV+
- [ ] `POST /api/strategy-a/calculate` accepte cote boost + cotes marché → retourne EV + mise

---

### Story 3.2 — Frontend page Stratégie A
**Points : 3**

Page `/strategy-a` : affichage des boosts EV+ du jour + calculateur manuel.

**CA :**
- [ ] Liste des boosts EV+ du jour avec : événement, cote boostée, cote normale, EV%, mise conseillée, RF
- [ ] Formulaire calculateur manuel : saisie cote boost + cotes marché → résultat instantané
- [ ] Tooltips (?) sur EV, RF, mise conseillée → lien vers `/docs`
- [ ] Bouton "Simuler ce pari" → pré-remplit le formulaire simulation
- [ ] Affichage alerte si scraper Betclic en erreur

---

**Epic 3 — Total : 6 points**

---

## Epic 4 — Stratégie B (Value Betting)

**Objectif** : Identifier les value bets sur marchés secondaires (corners, BTTS, aces, double fautes, cartons) avec EV+ calculé par les modèles.

---

### Story 4.1 — Backend niches foot (corners, BTTS, cartons)
**Points : 5**

`strategy_b.py` : calcul value bets sur 3 niches foot via Dixon-Coles et Poisson.

**CA :**
- [ ] Niche `corners` : `P(corners > N)` via Poisson, value si `cote_betclic / cote_juste - 1 > 0`
- [ ] Niche `btts` : `P(BTTS)` via Dixon-Coles
- [ ] Niche `cartons` : modèle simple basé historique arbitre (paramètre `cards_rate_{arbitre}`)
- [ ] `GET /api/strategy-b/bets` retourne value bets actifs triés par EV
- [ ] Chaque bet : `{niche, événement, p_estimée, cote_juste, cote_betclic, value%, ev, rf, mise}`

---

### Story 4.2 — Backend niches tennis (aces, double fautes, tie-breaks)
**Points : 5**

Étendre `strategy_b.py` avec 3 niches tennis via Poisson + Markov.

**CA :**
- [ ] Niche `aces` : `P(aces > N)` via Poisson avec `ace_rate(surface)`
- [ ] Niche `double_faults` : Poisson sur taux historique par surface
- [ ] Niche `tiebreaks` : `P(au moins 1 tie-break)` via Markov
- [ ] Filtres frontend : sport, surface, niche, EV minimum

---

### Story 4.3 — Frontend page Stratégie B
**Points : 3**

Page `/strategy-b` : value bets par niche avec filtres.

**CA :**
- [ ] Tableau des value bets actifs avec filtres : sport / surface / niche / EV min
- [ ] Tri par EV décroissant par défaut
- [ ] Chaque ligne : niche, événement, value%, EV, RF, mise conseillée
- [ ] Tooltips (?) sur value bet, niche, RF
- [ ] Bouton "Simuler ce pari"

---

**Epic 4 — Total : 13 points**

---

## Epic 5 — Stratégie C (CLV Tracker)

**Objectif** : Enregistrer cotes d'ouverture et de clôture, calculer CLV par pari et CLV moyen du portefeuille comme KPI de santé.

---

### Story 5.1 — Backend CLV
**Points : 3**

`strategy_c.py` : calcul CLV par pari et agrégats.

**CA :**
- [ ] `CLV_pari = cote_prise / cote_clôture - 1` calculé à la résolution du pari
- [ ] `CLV_moyen = moyenne(CLV_i)` sur tous paris résolus de la stratégie
- [ ] Test z : `z = CLV_moyen / (std_CLV / √N)` — significatif si z > 1.645
- [ ] `GET /api/strategy-c/clv` retourne : CLV par pari, CLV moyen, z-score, N paris

---

### Story 5.2 — Alertes mouvement de cotes
**Points : 3**

Détecter les cotes en baisse significative dans `odds_history` (signal de mouvement sharp).

**CA :**
- [ ] Calcule variation cote depuis ouverture pour chaque événement actif
- [ ] Alerte si variation > 5% en baisse (marché qui bouge)
- [ ] `GET /api/strategy-c/alerts` retourne événements avec mouvement détecté
- [ ] Utilise l'index `idx_odds_event` pour les requêtes (pas de full scan)

---

### Story 5.3 — Frontend page Stratégie C
**Points : 2**

Page `/strategy-c` : tableau CLV + alertes mouvements.

**CA :**
- [ ] Tableau des paris tracés : cote prise, cote clôture, CLV%, statut
- [ ] KPI en haut : CLV moyen, z-score, interprétation ("edge prouvé" / "pas encore significatif")
- [ ] Section alertes : événements avec mouvement de cote détecté
- [ ] Tooltips (?) sur CLV, z-score, sharp

---

**Epic 5 — Total : 8 points**

---

## Epic 6 — Dashboard & Portefeuilles

**Objectif** : Vue globale des 3 portefeuilles avec courbes de performance comparées et KPIs en temps réel.

---

### Story 6.1 — Backend dashboard
**Points : 3**

`GET /api/dashboard` agrège KPIs et données courbes pour les 3 portefeuilles.

**CA :**
- [ ] Retourne pour chaque stratégie : capital actuel, ROI%, CLV moyen, % paris EV+, drawdown max, Brier Score
- [ ] Retourne série temporelle capital par stratégie (pour courbes Chart.js)
- [ ] Retourne statut scraper (alerte rouge si erreur)
- [ ] Réponse en < 500ms

---

### Story 6.2 — Page simulation (enregistrement des paris)
**Points : 5**

Page `/simulation` : enregistrer un pari, saisir son résultat, historique.

**CA :**
- [ ] Formulaire "Nouveau pari" : stratégie, marché, sport, cote prise, mise, p_estimée, EV
- [ ] Bouton "Résoudre" sur chaque pari en cours : saisir résultat + cote clôture
- [ ] `portfolio_after` mis à jour automatiquement après résolution
- [ ] Historique des paris avec colonnes : date, événement, EV espéré, EV réalisé, résultat, impact portefeuille
- [ ] Filtres : stratégie, statut (en cours / résolu), période

---

### Story 6.3 — Frontend dashboard avec courbes comparées
**Points : 5**

Page `/` (dashboard) : courbes Chart.js superposées + KPIs.

**CA :**
- [ ] Courbe de performance : 3 lignes (A, B, C) sur même graphique, axe X = date, axe Y = capital ou ROI%
- [ ] Filtre période : 7j / 30j / tout
- [ ] KPIs par stratégie : ROI, CLV moyen, drawdown max, Brier Score — en vert/rouge selon seuils PRD
- [ ] Alerte scraper visible si erreur
- [ ] Chargement < 2s

---

**Epic 6 — Total : 13 points**

---

## Epic 7 — Moteur d'Apprentissage

**Objectif** : Brier Score glissant, mise à jour Bayésienne des paramètres, analyse des erreurs, détection niches dégradées.

---

### Story 7.1 — Brier Score glissant + alertes
**Points : 3**

`calibration.py` : BS glissant sur fenêtre 50 paris, alerte si dérive.

**CA :**
- [ ] `brier_score_rolling(bets, window=50)` → float
- [ ] `calibration_curve(bets, n_bins=10)` → dict pour graphique frontend
- [ ] Alerte automatique si BS > 0.22 : flag dans dashboard
- [ ] BS recalculé après chaque résolution de pari

---

### Story 7.2 — Mise à jour Bayésienne des paramètres
**Points : 5**

`bayesian_update.py` : recalibrer `att_i`, `def_i`, `ace_rate` après chaque résultat.

**CA :**
- [ ] `update_param(model_name, param_name, x_obs, sigma_obs)` → nouveau `param_value` + `confidence`
- [ ] Pondération récence : matchs récents = poids plus élevé (décroissance exponentielle λ=0.1)
- [ ] Déclenché automatiquement après `resolve-bet`
- [ ] Paramètres mis à jour dans `model_params`

---

### Story 7.3 — Analyse "Pourquoi j'ai perdu"
**Points : 5**

`error_explainer.py` : contribution de chaque feature à l'erreur de prédiction.

**CA :**
- [ ] `explain_error(bet)` → liste `[(feature, contribution), ...]` triée par `|contribution|`
- [ ] Contribution calculée via dérivée partielle numérique : `∂erreur/∂f_i × valeur_f_i`
- [ ] Génère une phrase lisible : *"Le ace_rate de Zverev sur terre était sous-estimé de 40%"*
- [ ] Stocké dans `bets.features_json` après calcul
- [ ] Affiché dans l'historique de simulation

---

### Story 7.4 — Détection niches dégradées + ranking
**Points : 3**

Détecter si une niche perd son edge et ranker les niches par ROI récent.

**CA :**
- [ ] Alerte si `EV_réalisé_moyen < EV_espéré × 0.5` sur N ≥ 30 paris d'une niche
- [ ] Ranking niches par ROI sur 30 derniers paris (mis à jour en temps réel)
- [ ] `GET /api/learning/niches` retourne ranking + alertes dégradation
- [ ] Mis à jour dans `niche_performance` après chaque résolution

---

### Story 7.5 — Frontend page Apprentissage
**Points : 3**

Page `/learning` : calibration, erreurs, ranking niches.

**CA :**
- [ ] Courbe de calibration (p_estimée vs fréquence réelle) — Chart.js scatter
- [ ] Tableau erreurs récentes avec colonne "explication principale"
- [ ] Heatmap performances : niche × sport × surface (couleur = ROI)
- [ ] Ranking niches : tableau trié par ROI 30j avec badge "dégradée" si alerte
- [ ] Bouton "Forcer recalibration" → `POST /api/learning/recalibrate`

---

**Epic 7 — Total : 19 points**

---

## Epic 8 — Documentation & Tooltips

**Objectif** : Page de documentation encyclopédique couvrant tous les concepts, avec tooltips (?) sur chaque terme technique dans l'app.

---

### Story 8.1 — Système tooltips global
**Points : 3**

`js/core/tooltips.js` : tooltips (?) universels dans toute l'app.

**CA :**
- [ ] Tout élément avec classe `tooltip-trigger` affiche un popup au hover
- [ ] Le popup contient : définition courte + lien ancré vers `/docs#terme`
- [ ] Fonctionne sur desktop (hover), pas de dépendance externe
- [ ] Termes couverts : EV, Vig, Value bet, Kelly, CLV, De-vigging, Brier Score, Dixon-Coles, Drawdown, Bankroll, Sharp, Niche, Edge, RF

---

### Story 8.2 — Page Documentation
**Points : 5**

Page `/docs` : 9 sections encyclopédiques avec navigation par ancre.

**CA :**
- [ ] 9 sections présentes : Fondamentaux · 3 Stratégies · Modèles maths · Capital · Facteur Risque · CLV · Apprentissage · Glossaire · Ressources
- [ ] Navigation latérale avec ancres (scroll smooth)
- [ ] Chaque stratégie : principe simple + formules + exemple chiffré de A à Z
- [ ] Glossaire interactif : 15 termes minimum avec lien vers section détaillée
- [ ] Chaque tooltip (?) de l'app pointe vers la bonne ancre de cette page

---

**Epic 8 — Total : 8 points**

---

## Récapitulatif

| Epic | Nom | Points | Dépendances |
|------|-----|--------|-------------|
| 0 | Setup Projet | 10 | — |
| 1 | Scrapers | 19 | Epic 0 |
| 2 | Modèles | 23 | Epic 1 (bootstrap FBref) |
| 3 | Stratégie A | 6 | Epic 2 |
| 4 | Stratégie B | 13 | Epic 2 |
| 5 | Stratégie C | 8 | Epic 1 (odds_history) |
| 6 | Dashboard & Simulation | 13 | Epics 3, 4, 5 |
| 7 | Apprentissage | 19 | Epic 6 |
| 8 | Documentation & Tooltips | 8 | Epic 6 |
| **TOTAL** | | **119 points** | |

**Chemin critique** : 0 → 1 → 2 → 3+4+5 (parallèle) → 6 → 7+8 (parallèle)

**Premier sprint recommandé** : Epic 0 complet + Story 1.1 (FBref bootstrap) — base solide avant tout le reste.

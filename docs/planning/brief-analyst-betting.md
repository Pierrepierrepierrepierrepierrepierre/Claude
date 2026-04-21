# Brief Analyste — BettingEdge App
*Rédigé par Mary (Analyste BMAD) — 2026-04-21*

---

## Contexte & Objectif

Construire une application web personnelle d'aide à la décision pour les paris sportifs, centrée sur **l'espérance positive du portefeuille**. Pas de gain garanti par pari — mais un edge mathématique prouvable sur la durée.

**Utilisateur** : Pierre, data analyst/engineer, débutant en capital, expert en modélisation.
**Bookmaker initial** : Betclic uniquement.
**Sports couverts** : Football + Tennis.
**Poker** : hors scope pour l'instant.

---

## Principe fondamental

> Une cote bookmaker encode une probabilité implicite faussée par la marge (le "vig"). L'objectif est de trouver des situations où notre estimation de la probabilité réelle dépasse celle encodée dans la cote — créant ainsi une **espérance de gain positive (EV+)**.

`EV = prob_estimée × cote - 1`
- EV > 0 → pari intéressant
- EV = 0 → neutre
- EV < 0 → à éviter (la majorité des paris standards)

---

## Les 3 Stratégies

### Stratégie A — Exploitation des Cotes Boostées (Boosts EV)

**Principe** : Betclic propose des "Super Boosts" promotionnels. Certains ont une EV positive si notre modèle estime la probabilité réelle supérieure à `1 / cote_boostée`.

**Ce que l'app fait** :
- Détecter / saisir manuellement les boosts disponibles sur Betclic
- Calculer la probabilité implicite du boost
- Comparer à notre estimation maison (modèle foot/tennis)
- Afficher l'EV et la mise recommandée (Kelly fractionné)

**Mathématiques clés** :
- Probabilité implicite : `p_implicite = 1 / cote`
- EV boost : `EV = p_estimée × cote_boostée - 1`
- Risque réel : un boost EV+ reste un pari avec des pertes possibles. La rentabilité se démontre sur un **volume suffisant de paris** (loi des grands nombres).

**Risque de ban** : très faible (on joue les promos officielles).

---

### Stratégie B — Value Betting sur Marchés Secondaires

**Principe** : Les marchés secondaires (corners, aces, cartons, buteur anytime, ligues exotiques) sont moins couverts par les algorithmes des bookmakers. Un modèle statistique affûté peut y trouver des EV+ systématiquement.

**Marchés cibles** :
- **Tennis** : nombre d'aces par match, double fautes, sets joués, tie-breaks
- **Foot** : corners totaux, BTTS (les deux équipes marquent), cartons jaunes, xG-based handicap sur Ligue 2 / Eredivisie / Championship

**Ce que l'app fait** :
- Nourrir un modèle de probabilité maison par marché (basé sur historique stats)
- Comparer la cote Betclic à la cote "juste" modélisée
- Alerter quand EV > seuil paramétrable

**Mathématiques clés** :
- Cote juste : `cote_juste = 1 / p_estimée`
- Value : `value = cote_betclic / cote_juste - 1` (positif = value bet)
- Mise Kelly : `f = (p × b - q) / b` où b = cote-1, p = prob estimée, q = 1-p
- Kelly fractionné recommandé : `f* = Kelly × 0.25` (réduction variance)

**Risque de ban** : faible (marchés peu scrutinés, volumes moindres).

---

### Stratégie C — Closing Line Value (CLV)

**Principe** : Les bookmakers ajustent leurs cotes au fil du temps à mesure que l'argent "sharp" (parieurs professionnels) entre. Parier tôt sur une cote que le bookmaker va abaisser = battre la ligne de clôture = preuve d'edge.

**Ce que l'app fait** :
- Enregistrer la cote au moment du pari
- Enregistrer la cote de clôture (juste avant le match)
- Calculer le CLV : `CLV = cote_pari / cote_cloture - 1`
- Afficher le CLV moyen du portefeuille (KPI de santé du modèle)

**Mathématiques clés** :
- `CLV > 0` sur la durée = le modèle prédit mieux que le marché
- Le CLV est un indicateur **prospectif** de rentabilité, plus fiable que le P&L court terme

**Risque de ban** : modéré (Betclic surveille les profils CLV+ sur marchés principaux).

---

## Modèles Mathématiques Détaillés

### Stratégie A — De-vigging + Consensus multi-marchés

**De-vigging (méthode multiplicative) :**
```
p_implicite_i = 1 / cote_i
vig = Σ p_implicite_i - 1
p_normalisée_i = p_implicite_i / Σ p_implicite_j
```

**Consensus multi-marchés :**
```
p_consensus = moyenne_pondérée(p_1X2, p_AH, p_OU)    # poids = liquidité estimée
EV_boost = p_consensus × cote_boostée - 1
Condition : EV_boost > seuil (ex: 3%) pour absorber l'erreur d'estimation
```

**Kelly fractionné :**
```
f_kelly = (p × b - q) / b      où b = cote-1, q = 1-p
f* = f_kelly × κ               κ ∈ [0.1, 0.33], défaut = 0.25
```

---

### Stratégie B — Modèles par marché

**B1. Tennis — Aces (Poisson)**
```
λ_total = λ_A + λ_B
λ_serveur = ace_rate(surface) × E[jeux_de_service]
E[jeux_de_service] = f(p_hold_A, p_hold_B, format)   # modèle Markov

P(aces > N) = 1 - Σ_{k=0}^{N} e^(-λ) × λ^k / k!
cote_juste = 1 / P_modèle
value = cote_betclic / cote_juste - 1
```

**B2. Football — Buts (Dixon-Coles)**
```
λ_home = att_home × def_away × γ_home    # γ ≈ 1.15-1.25
λ_away = att_away × def_home

Correction scores bas :
τ(0,0) = 1 - λ_h×λ_a×ρ  |  τ(1,0) = 1+λ_a×ρ  |  τ(0,1) = 1+λ_h×ρ  |  τ(1,1) = 1-ρ

P(BTTS)     = P(buts_h≥1) × P(buts_a≥1)
P(Over 2.5) = Σ_{x+y>2} P_DC(x,y)
```

**B3. Football — Corners (Poisson)**
```
λ_total = λ_home + λ_away
λ_home  = moy_corners_home × (1 + α × diff_xG_espérée)
```

---

### Stratégie C — CLV et significativité statistique

```
CLV_pari    = cote_pari / cote_clôture - 1
CLV_moyen   = (1/N) × Σ CLV_i

Test z : z = CLV_moyen / (std_CLV / √N)
Significatif si z > 1.645 (p < 0.05)
```

---

## Calcul du Facteur Risque — Modèle Composite

Score RF ∈ [0, 1] affiché sur chaque pari. 5 dimensions :

```
F_modèle   = 1 - exp(-N_similaires / 50)              # volume historique
F_ev       = min(1, EV/0.15) × (1 - max(0,(EV-0.15)/0.35))  # EV optimal ~15%
F_variance = 1 / (1 + p×(1-p)×cote²)                 # variance du pari
F_calib    = 1 - brier_score/0.25                     # calibration modèle
F_clv      = sigmoid(CLV_moyen × 20)                  # track record

RF = 0.30×F_modèle + 0.20×F_ev + 0.15×F_variance + 0.20×F_calib + 0.15×F_clv
```

**Mise finale avec RF :**
```
mise = min(f_kelly × κ × RF × portefeuille, 0.05 × portefeuille)
```

**Interprétation affichée dans l'app** :

---

## Sizing des Mises (Gestion du Portefeuille)

- **Kelly fractionné** comme base : mise = `f* × portefeuille_stratégie`
- Plafond par pari : max 5% du portefeuille de la stratégie (protection drawdown)
- Chaque stratégie a **son propre portefeuille isolé** (capital fictif en simulation, capital réel en live)
- Pas de transfert de capital entre stratégies dans l'interface

---

## Fonctionnalités de l'App

### Pages principales

| Page | Description |
|------|-------------|
| **Dashboard** | Vue globale des 3 portefeuilles, courbes de performance comparées |
| **Stratégie A** | Interface boosts Betclic + EV calculator |
| **Stratégie B** | Value bets suggérés par marché/sport |
| **Stratégie C** | Suivi CLV + alertes ligne de clôture |
| **Simulation** | Mode papier avec argent fictif, historique des paris simulés |
| **Documentation** | Guide encyclopédique : stratégies, maths, glossaire, concepts paris, tutoriels |

### Fonctionnalités transversales

- **Tooltips (?)** sur chaque terme technique partout dans l'app : EV, Kelly, CLV, vig, value bet, etc. (lien vers la section doc correspondante au clic)
- **Courbes de performance** par stratégie + comparaison croisée
- **Facteur risque** affiché sur chaque pari proposé
- **Mise recommandée** calculée automatiquement (Kelly fractionné)
- **Historique des paris** simulés avec résultats, EV réalisé vs EV espéré
- **KPIs** : ROI, CLV moyen, % paris EV+, drawdown max

### Architecture code (isolation des stratégies)

```
src/
├── strategies/
│   ├── strategy-a-boosts.js      # Indépendant
│   ├── strategy-b-value.js       # Indépendant
│   └── strategy-c-clv.js         # Indépendant
├── niches/                       # Branchables indépendamment sur Stratégie B
│   ├── corners.js
│   ├── btts.js
│   ├── cards-referee.js
│   ├── double-faults.js
│   └── tiebreaks.js
├── core/
│   ├── kelly.js                  # Calcul Kelly (partagé)
│   ├── ev.js                     # Calcul EV (partagé)
│   ├── poisson.js                # Distributions (partagé)
│   ├── dixon-coles.js            # Modèle foot (partagé)
│   └── risk-factor.js            # Calcul facteur risque (partagé)
├── learning/
│   ├── calibration.js            # Brier score glissant
│   ├── bayesian-update.js        # Mise à jour paramètres
│   ├── error-explainer.js        # "Pourquoi j'ai perdu"
│   └── niche-ranker.js           # ROI par niche, détection dégradation
├── simulation/
│   └── portfolio.js              # Portefeuille fictif par stratégie
└── ui/
    ├── dashboard.js
    ├── learning.js               # Page apprentissage + calibration
    ├── docs.js                   # Documentation + tooltips
    └── charts.js                 # Courbes performance
```

---

## Page Documentation — Contenu Exhaustif

La documentation est une **référence autonome** : Pierre doit pouvoir comprendre n'importe quel concept de l'app sans chercher ailleurs.

### Structure de la page

**1. Concepts fondamentaux des paris**
- Comment fonctionne une cote (décimale, fractionnaire, américaine)
- La marge bookmaker (vig) : pourquoi l'espérance est négative par défaut
- Probabilité implicite et comment la calculer
- Espérance mathématique (EV) : définition, formule, exemples concrets
- Loi des grands nombres : pourquoi EV+ ne garantit pas de gagner chaque pari
- Variance et drawdown : qu'est-ce qu'une mauvaise série normale ?

**2. Les 3 stratégies — explication pédagogique complète**

Pour chaque stratégie :
- Principe en langage simple (sans formule)
- Formules mathématiques détaillées avec exemples chiffrés
- Quand l'utiliser / quand éviter
- Risques et limites
- Exemple de pari concret de A à Z

**3. Modèles mathématiques**
- De-vigging : pourquoi et comment extraire `p_réelle` d'une cote
- Poisson : intuition, formule, application tennis et corners
- Dixon-Coles : pourquoi Poisson simple sous-estime les scores bas
- Modèle Markov tennis : comment calculer les probabilités de jeux/sets
- Calibration et Brier Score : comment mesurer la qualité d'un modèle de proba
- Mise à jour Bayésienne : comment intégrer les nouveaux résultats

**4. Gestion du capital**
- Kelly Criterion : dérivation mathématique, intuition
- Pourquoi Kelly fractionné (× 0.25) : bankroll management et évitement de la ruine
- Plafond à 5% par pari : protection contre le drawdown extrême
- Portefeuilles séparés par stratégie : diversification de l'edge

**5. Le Facteur Risque — guide de lecture**
- Signification de chaque dimension (F_modèle, F_ev, F_variance, F_calib, F_clv)
- Comment interpréter le score composite
- Pourquoi un EV très élevé est suspect (outlier, erreur de cote imminente)
- Tableau de correspondance score → recommandation de mise

**6. Closing Line Value (CLV)**
- Pourquoi la cote de clôture est le meilleur estimateur de la vraie probabilité
- Comment lire son CLV moyen : seuils d'interprétation
- Test de significativité z : qu'est-ce qu'un edge statistiquement prouvé ?
- Combien de paris faut-il pour être sûr d'avoir un edge ?

**7. Le moteur d'apprentissage**
- Comment l'app apprend de chaque pari résolu
- Lecture de la courbe de calibration
- Comprendre les "explications d'erreur" générées
- Détection de niche dégradée : comment réagir

**8. Glossaire interactif**
Tous les termes techniques avec définition courte + lien vers la section détaillée :

| Terme | Définition courte |
|-------|------------------|
| EV (Expected Value) | Gain moyen attendu par unité misée |
| Vig / Marge | Pourcentage prélevé par le bookmaker |
| Value bet | Pari où notre EV estimé est positif |
| Kelly | Formule de mise optimale selon l'edge |
| CLV | Ratio cote prise / cote de clôture |
| De-vigging | Extraction de la prob réelle depuis une cote |
| Brier Score | Mesure d'erreur d'un modèle de probabilité |
| Dixon-Coles | Modèle Poisson corrigé pour les faibles scores |
| Drawdown | Perte maximale sur une période |
| Bankroll | Capital total alloué aux paris |
| Sharp | Parieur professionnel dont les mises font bouger les cotes |
| Niche | Marché spécifique où le bookmaker modélise mal |
| Edge | Avantage mathématique sur le bookmaker |
| CLV+ | Battre la ligne de clôture → preuve d'edge |
| Portefeuille | Capital isolé par stratégie |

**9. Ressources externes recommandées** *(liens vers sites publics)*
- Sources de stats foot (FBref, Understat, Transfermarkt)
- Sources de stats tennis (Tennis Abstract, ATP/WTA stats)
- Outils de comparaison de cotes publics
- Lectures recommandées : articles académiques sur Dixon-Coles, Kelly

---

## Moteur d'Apprentissage — Modèle Auto-Améliorant

### Principe

Après chaque pari résolu (gagné ou perdu), l'app analyse **pourquoi** le modèle avait raison ou tort, et recalibre ses paramètres automatiquement.

### Ce qu'on enregistre à la résolution de chaque pari

```
{
  pari_id, stratégie, marché, sport,
  p_estimée,          # probabilité prédite par notre modèle
  cote_prise,         # cote au moment du pari
  cote_clôture,       # proxy de la "vraie" probabilité marché
  résultat,           # 1 = gagné, 0 = perdu
  ev_espéré,          # EV calculé avant le pari
  ev_réalisé,         # résultat - mise (normalisé)
  features: {         # variables explicatives au moment du pari
    surface, ligue, arbitre, h2h_récent, forme_5_matchs,
    λ_utilisé, ρ_utilisé, κ_utilisé, ...
  }
}
```

### Boucle d'apprentissage

**1. Calibration automatique (Brier Score continu)**

```
brier_score_glissant = moyenne_mobile(résultat - p_estimée)²   # fenêtre = 50 paris
```
Si `brier_score > seuil_alerte` → notification "modèle dérivé, recalibration recommandée"

**2. Mise à jour Bayésienne des paramètres**

Pour les paramètres clés (ex: `ace_rate` d'un joueur, `att_i` d'une équipe) :

```
# Prior = estimation actuelle
# Likelihood = résultats observés récents
# Posterior = nouvelle estimation

μ_post = (μ_prior × σ²_obs + x_obs × σ²_prior) / (σ²_prior + σ²_obs)
```

Les paramètres se mettent à jour **après chaque nouveau résultat** avec une fenêtre glissante pondérée (matchs récents = poids plus élevé, décroissance exponentielle).

**3. Analyse des erreurs — "Pourquoi j'ai perdu"**

Pour chaque pari résolu, l'app calcule la contribution de chaque feature à l'erreur :

```
erreur = résultat - p_estimée

Pour chaque feature f_i :
  contribution_i = ∂erreur/∂f_i × valeur_f_i    # dérivée partielle numérique

Ranking des features par |contribution_i| → affichage "ce qui a le plus dévié"
```

Exemples d'explications générées :
- *"Le taux de double fautes de Zverev sur terre battue était 40% sous-estimé"*
- *"L'arbitre Turpin donne historiquement 30% plus de cartons que prévu par le modèle"*
- *"La forme sur 5 matchs n'était pas intégrée — l'équipe sortait de 3 défaites"*

**4. Détection de niches dégradées**

```
EV_réalisé_moyen_par_niche = moyenne(ev_réalisé) par type de marché

Si EV_réalisé < EV_espéré × 0.5 sur N ≥ 30 paris d'une niche :
  → alerte "niche potentiellement nerfée ou sur-ajustée"
```

C'est ce qui permettra de détecter si une niche (ex: aces ATP) se dégrade — exactement comme le parieur que vous citiez.

**5. A/B implicite entre niches**

Chaque niche de la Stratégie B a son propre historique de performance. L'app rankera les niches par **ROI net sur 30 derniers paris** pour guider l'allocation du capital.

### Stockage

Tout en `localStorage` (v1) → export CSV/JSON possible pour analyse externe dans un notebook Python si besoin.

### Interface "Apprentissage"

- Page dédiée : courbe de calibration (p_estimée vs fréquence réelle)
- Tableau des paris résolus avec colonne "explication principale de l'erreur"
- Heatmap des performances par niche × sport × surface
- Bouton "Forcer recalibration" si Pierre veut déclencher manuellement

---

## Hors scope (v1)

- Poker en ligne
- Multi-bookmakers (possible en v2)
- Scraping automatique Betclic (à évaluer selon faisabilité technique)
- Paris live / in-play

---

## Prochaine étape recommandée

Passer à **John (PM)** pour transformer ce brief en PRD formel avec user stories, priorités et critères d'acceptance.


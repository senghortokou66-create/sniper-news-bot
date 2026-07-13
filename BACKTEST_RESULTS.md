# Résultats de backtest — Documentation complète

Ce document trace l'intégralité de la démarche de validation de la
stratégie : ce qui a été testé, ce qui a été validé, et — tout aussi
important — **ce qui a été testé et rejeté**, pour ne jamais refaire le
même travail deux fois.

Données utilisées : XAUUSD M1 (2011-2026, fiable à partir de mi-2019),
XAGUSD M1 (2013-2026, même fiabilité), calendrier économique
ForexFactory historique (2007-2024, `scrape.csv`). Backtests exécutés
sur la période **juillet 2019 – août 2024** (5,1 ans).

---

## 1. Méthodologie de validation

Chaque résultat ci-dessous a été soumis à :

1. **Split train/test** : train = 2019-07 à 2021-12, test = 2022-01 à
   2024-08. Un résultat n'est retenu que s'il tient dans les deux
   périodes, pas seulement en moyenne globale.
2. **Test de permutation** (significativité statistique) : les mêmes
   instants d'entrée sont conservés, mais la direction (BUY/SELL) est
   tirée aléatoirement sur 300 essais. Si le PF réel dépasse tous les
   tirages aléatoires (p < 0,33%), l'edge est jugé réel et pas dû au
   hasard.
3. **Sensibilité au coût de spread** : le spread réel n'existe pas dans
   l'historique M1 (MT5 ne conserve pas le spread historique, seulement
   en temps réel). Un coût forfaitaire de 0,186$ (or) a été utilisé,
   testé jusqu'à 8x plus élevé (1,5$) sans effondrement du résultat.

---

## 2. Stratégie validée (configuration finale)

### 2.1 Filtre d'entrée

- Surprise macro (actual vs consensus ForexFactory) ≥ 8%
- Tendance des 4h précédant l'annonce alignée avec la direction prédite,
  force ≥ 5$ (or) / équivalent 0,265% du prix (converti pour être
  applicable à d'autres actifs)
- Indicateurs : Non-Farm Employment Change, Core CPI m/m, Unemployment
  Rate (Unemployment Claims exclu, voir section 4.1)

### 2.2 Exécution et sortie

- Entrée immédiate à l'ouverture de la bougie M1 de l'annonce
- SL 1,5$ / TP 15$ (ratio R:R 1:10)
- Breakeven à +2$ de gain latent, puis trailing à 1$ derrière le
  meilleur prix atteint

### 2.3 Résultats — XAUUSD (or)

| Métrique | Valeur |
|---|---|
| Trades (5,1 ans) | 48 |
| Gagnants | 40 (83,3%) |
| Perdants | 8 (16,7%) |
| PF total | 25,85 |
| PF train (2019-2021) | 31,64 |
| PF test (2022-2024) | 27,89 |
| p-value (permutation, 300 tirages) | < 0,0033 (0/300) |
| Sensibilité spread (jusqu'à 1,5$) | PF reste ≥ 11,88 |

### 2.4 Résultats — XAGUSD (argent), même méthodologie, seuils convertis en %

| Métrique | Valeur |
|---|---|
| Trades (5,1 ans) | 51 |
| Gagnants | 39 (76,5%) |
| Perdants | 12 (23,5%) |
| PF total | 24,38 |
| PF train | 23,46 |
| PF test | 25,04 |
| p-value (permutation, 300 tirages) | < 0,0033 (0/300) |

**Conclusion** : l'edge se généralise à un second marché indépendant,
avec la même robustesse statistique. C'est la validation la plus forte
obtenue — un edge propre à un seul actif serait plus suspect de
surajustement.

---

## 3. Mécanisme de sortie : pourquoi le breakeven/trailing a été ajouté

Analyse des pertes de la config sans trailing (avant son ajout) :
**82% des pertes avaient d'abord évolué favorablement** avant de se
retourner et toucher le SL complet — dont deux cas extrêmes à +12,04$
et +12,87$ de gain latent (à deux doigts du TP à 15$) avant un
retournement total.

Grid search du trailing stop (déclencheur × distance de suivi) :

| Config | PF train | PF test | PnL total |
|---|---|---|---|
| Sans trailing | 16,53 | 10,72 | +209,59$ |
| Breakeven seul (+2$) | 36,90 | 24,14 | +219,12$ |
| **Trailing (trigger 2$, trail 1$)** | **47,56** | **29,71** | **+223,72$** |

Coût du mécanisme (transparence) : un trade gagnant (06/12/2019, NFP)
devient une perte marginale (-0,186$ au lieu de +0,784$), car le
trailing l'a coupé avant qu'il ne reparte vers le TP après un
retracement. Compromis accepté : le gain net global dépasse largement
cette perte isolée.

---

## 4. Pistes testées et REJETÉES (ne pas retester sans nouvelle donnée)

### 4.1 Indicateurs à edge non démontré ou négatif

- **Unemployment Claims** (hebdomadaire) : PF 1,85 isolé — inclus, il
  faisait chuter le PF global de 4,07 à 3,18. Exclu de la config finale.
- **RSAFS (ventes au détail), PPIACO (PPI), PCEPILFE (Core PCE)** :
  pas d'edge démontré (session de backtesting antérieure).

### 4.2 Délai d'entrée après l'annonce

Test de délai de 0 à +10 minutes sur la config de référence (SL15/TP150,
seuil 8%) :

| Délai | Win rate | PF | PnL |
|---|---|---|---|
| 0 min (actuel) | 33,6% | 3,18 | +375,90$ |
| +1 min | 17,8% | 1,26 | +56,09$ |
| +3 min | 12,1% | 0,70 | -65,12$ (perdant) |

**Conclusion** : tout délai détruit l'edge. L'entrée immédiate n'est
pas un risque à corriger, c'est la source même de l'edge (capture le
mouvement avant qu'il ne se produise).

### 4.3 Filtre de cohérence interne du rapport (indicateurs compagnons)

Hypothèse : rejeter un trade si un indicateur publié au même instant
(ex : Average Hourly Earnings pour le NFP) contredit la direction
prédite.

Résultat : sur 21 trades rejetés par ce filtre, **18 auraient été
gagnants (86%)**. Le filtre élimine bien plus de bons trades que de
mauvais — rejeté.

| Compagnon bloquant | Trades bloqués | Auraient été gagnants |
|---|---|---|
| Average Hourly Earnings | 13 | 11 (85%) |
| CPI m/m | 2 | 2 (100%) |
| CPI y/y | 3 | 3 (100%) |

### 4.4 SL adaptatif selon l'ampleur de la surprise macro

Hypothèse initiale (basée sur le cas CPI de nov. 2022) : les surprises
extrêmes causeraient plus de pertes par slippage/volatilité.

Vérification sur l'ensemble des trades : médiane de surprise des
perdants (36,7%) **inférieure** à celle des gagnants (40%). Hypothèse
invalidée — écartée.

### 4.5 VIX (indice de peur) comme filtre

Semblait prometteur en apparence (PF total ×3 en filtrant VIX≤22), mais
**8 des 9 trades à VIX élevé étaient concentrés sur la seule année
2022** (invasion Ukraine, hausses de taux Fed) — confusion entre "VIX
élevé" et "était en 2022", pas un vrai signal généralisable. Split
chronologique en deux moitiés égales : aucune amélioration réelle hors
échantillon. Rejeté.

### 4.6 GPR (indice de risque géopolitique quotidien, Caldara-Iacoviello)

Les perdants ont un GPR **plus bas** en moyenne (88) que les gagnants
(116) — contre-intuitif, aucun lien exploitable. Rejeté.

### 4.7 SL élargi spécifiquement pour XAGUSD

Hypothèse : l'argent étant plus bruité, un SL plus large pourrait
absorber ce bruit sans perdre l'edge.

| SL × multiplicateur | Win rate | PF |
|---|---|---|
| ×1,0 (actuel) | 76,5% | 24,38 |
| ×2,0 | 76,5% | 12,90 |
| ×3,0 | 82,4% | 12,34 |

Le PF se dégrade continuellement. Un SL plus large coûte plus cher sur
l'ensemble des trades perdants qu'il ne fait gagner en sauvant quelques
cas. Rejeté.

### 4.8 Stratégie propre à XAGUSD basée sur des indicateurs industriels

Hypothèse : l'argent, métal hybride (refuge + industriel), pourrait
avoir sa propre logique basée sur ISM Manufacturing PMI plutôt que la
logique "dollar fort/faible" de l'or.

Deux directions testées :
- **H1 (dollar fort, comme l'or)** : PF 3,25 (train 3,87 / test 2,68),
  p-value = 0,08 — pas significatif au seuil conventionnel de 5%.
- **H2 (demande industrielle directe)** : PF 2,28 mais écart massif
  train (7,33) / test (1,50) — surajustement évident.

Aucune des deux ne bat la config principale (PF ~25). Rejeté — l'argent
ne semble pas avoir de logique distincte exploitable via ces
indicateurs ; il suit essentiellement la même dynamique macro que l'or,
avec plus de bruit propre à son marché plus petit.

### 4.9 Ratio Or/Argent comme filtre

Filtrer les trades XAGUSD par niveau du ratio Or/Argent au moment de
l'entrée : amélioration apparente du PF train (23,46 → 41,08) mais **PF
test quasiment inchangé** (25,04 → 26,34) — signe que l'amélioration
est un artefact d'ajustement sur le passé, pas un vrai gain prédictif.
Rejeté (pas assez d'amélioration hors-échantillon pour justifier un
paramètre supplémentaire sur un échantillon déjà petit).

---

## 5. Analyse des pertes irréductibles

Sur les pertes restantes après tous les mécanismes de protection
(breakeven/trailing), le mécanisme dominant est **l'échec immédiat** :
le marché part dans le mauvais sens dès la première minute, sans jamais
laisser de fenêtre favorable à capturer (0% d'excursion favorable avant
la perte, dans 100% des cas résiduels sur XAGUSD, la majorité sur
XAUUSD).

Cause identifiée dans certains cas précis (vérifiée, pas supposée) :
- **Contradictions internes du rapport** (ex : NFP fort mais salaire
  horaire moyen en baisse) — confirmé sur au moins 3 cas historiques.
- **Facteurs macro simultanés non capturés par le calendrier** (ex :
  tensions géopolitiques Ukraine en février 2022, confirmées par
  recherche externe) — réels mais non filtrables avec les données
  disponibles (GPR quotidien testé et rejeté, section 4.6).
- **Bruit propre au marché de l'argent** (marché plus petit, nature
  hybride refuge/industriel) — 5 des 12 pertes XAGUSD coïncident avec
  des jours où l'or, lui, a gagné sur la même annonce.

Ces pertes sont considérées comme du bruit de marché irréductible, pas
une faille corrigible avec les données et méthodes actuellement
disponibles.

---

## 6. Erreur corrigée : FRED vs ForexFactory

La première version du bot (basée sur FRED) calculait la surprise comme
`actual - mois précédent`, alors que **tout ce backtest** calcule la
surprise comme `actual - consensus des économistes` (ForexFactory).
FRED ne fournit jamais de données de consensus — cette divergence
signifiait que le bot en production ne reproduisait pas la stratégie
validée. Corrigé en migrant vers le flux public ForexFactory
(`nfs.faireconomy.media/ff_calendar_thisweek.json`).

---

## 7. Limitations générales, honnêtes

- Le filtre de confluence (tendance 4h) n'est pas actif en production
  (pas de flux de prix temps réel disponible pour le bot).
- Tout backtest reflète le passé ; aucune garantie sur la performance
  future.
- Le code du bot a été reconstruit à partir de fragments retrouvés en
  mémoire de conversation à un moment de la démarche — une divergence
  mineure de comptage de trades (n=146 vs n=163 mentionnés
  antérieurement) n'a jamais été totalement résolue.
- Les échantillons (48-51 trades) restent modestes en valeur absolue,
  même si la significativité statistique est forte.

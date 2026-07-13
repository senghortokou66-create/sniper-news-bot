# Sniper News Bot — XAU/USD News Trading Signal

Bot Telegram gratuit qui envoie un signal de trading quand une annonce
macro-économique US (NFP, Core CPI, Taux de chômage) surprend
significativement le consensus des économistes.

Stratégie validée par backtest rigoureux sur **5,1 ans de données M1**
(juillet 2019 – août 2024), avec validation croisée train/test et test
de significativité statistique par permutation. Edge confirmé sur
**deux marchés indépendants** (XAUUSD et XAGUSD).

Voir [`BACKTEST_RESULTS.md`](./BACKTEST_RESULTS.md) pour le détail complet
de la méthodologie, des résultats et de tout ce qui a été testé et rejeté.

---

## Stratégie en résumé

**Signal d'entrée** : surprise macro (actual vs consensus ForexFactory)
≥ 8%, ET tendance des 4h précédant l'annonce déjà alignée avec la
direction prédite (force ≥ 0,265% du prix, soit ≈5$ sur l'or à son
prix moyen historique ~1888$).

**Exécution** : entrée immédiate à l'ouverture de la bougie de
l'annonce — **aucun délai, aucune confirmation**. Un délai, même d'une
minute, détruit la majeure partie de l'edge (voir BACKTEST_RESULTS.md,
section "Timing d'entrée").

**Actifs suivis en production** : XAUUSD (or) et XAGUSD (argent),
chacun avec son propre suivi de prix et son propre filtre de
confluence — un signal peut être confirmé sur l'un et pas sur l'autre.

**Gestion de sortie** : SL/TP et breakeven/trailing calculés
**dynamiquement en % du prix réel au moment du signal** (pas des pips
fixes) : SL ≈0,079% du prix, TP ≈0,79% (ratio R:R 1:10) :
1. Dès que le gain latent atteint ≈0,106% du prix → SL déplacé au prix
   d'entrée (perte plafonnée au coût du spread)
2. Puis le SL suit à ≈0,053% derrière le meilleur prix atteint, jusqu'au
   Take Profit ou jusqu'à la sortie

Ces pourcentages sont calibrés sur l'or (validés à 1,5$/15$ à son prix
moyen historique ~1888$) et se généralisent à l'argent (validés
indépendamment, voir tableau ci-dessous).

**Indicateurs surveillés** : Non-Farm Employment Change (NFP), Core CPI
m/m, Unemployment Rate. Unemployment Claims (hebdomadaire) a été
délibérément exclu — testé et démontré contre-productif seul (PF 1,85).

**Performance validée (backtest)** :

| Marché | Trades (5,1 ans) | Win rate | PF (test 2022-24) | Significativité |
|---|---|---|---|---|
| XAUUSD | 48 | 83,3% | 27,89 | p < 0,33% |
| XAGUSD | 51 | 76,5% | 25,04 | p < 0,33% |

---

## ✅ Filtre de confluence maintenant actif

**Le filtre de confluence (tendance des 4h) est actif depuis la version
la plus récente.** Source de prix : [gold-api.com](https://gold-api.com)
— gratuit, sans clé API, sans limite de requêtes sur l'endpoint prix
temps réel. Le bot enregistre un instantané de prix à chaque exécution
(toutes les 15 min) dans `state.json`, conserve une fenêtre glissante de
5h, et vérifie la tendance réelle avant chaque signal.

**Comportement selon le résultat de la vérification** :
- **Confluence confirmée** → signal envoyé, config complète validée
  (PF ~25-28)
- **Confluence absente** (tendance contraire ou trop faible) → signal
  **non envoyé**, uniquement loggé
- **Historique insuffisant** (bot récemment démarré/redémarré, moins de
  4h de données accumulées) → signal envoyé quand même, mais
  explicitement marqué comme non confirmé (edge plus faible attendu,
  PF ~4-5)

Le mécanisme de breakeven/trailing reste communiqué dans le message
Telegram pour exécution **manuelle** — le bot n'exécute aucun trade
lui-même (pas de connexion broker), il envoie uniquement des signaux.

---

## Architecture technique

- **Source de données calendrier** : flux public ForexFactory
  (`nfs.faireconomy.media/ff_calendar_thisweek.json`) — fournit
  actual/forecast/previous, gratuit, utilisé par la communauté MT4/MT5
  depuis des années. Remplace FRED (qui ne fournit jamais le consensus
  des économistes — voir `BACKTEST_RESULTS.md`, section "Erreur
  corrigée : FRED vs ForexFactory").
- **Source de prix (confluence)** : [gold-api.com](https://gold-api.com)
  — gratuit, sans clé, sans limite de requêtes sur l'endpoint temps
  réel. Symboles `XAU` (or) et `XAG` (argent) suivis en parallèle,
  chacun avec son propre historique de prix dans `state.json`.
- **Cache** : 30 min entre chaque appel au calendrier (le flux limite
  les requêtes).
- **Notification** : Telegram (Bot API).
- **Exécution** : GitHub Actions (gratuit), planifié périodiquement.
- **État persistant** : `state.json` (événements déjà traités, cache
  calendrier, dernier heartbeat).

### Variables d'environnement requises (GitHub Secrets)

| Variable | Usage |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram |
| `TELEGRAM_CHAT_ID` | ID du chat/canal de destination |

`FRED_API_KEY` n'est plus utilisée depuis la migration vers
ForexFactory — peut être supprimée des secrets sans impact.

---

## Historique des versions de la stratégie

1. **v1 (FRED, actual vs mois précédent)** — logique incorrecte, ne
   correspondait pas à la stratégie backtestée. Corrigée.
2. **v2 (7 indicateurs FRED, SL30/TP100)** — PF 2,4, sans validation
   train/test rigoureuse.
3. **v3 (4 indicateurs, SL15/TP150, sans Unemployment Claims)** — PF
   4,07-4,74, première validation train/test.
4. **v4 (confluence macro+tendance, breakeven/trailing)** — PF ~25-28,
   validée par permutation statistique, généralisée à XAGUSD. Filtre de
   confluence testé en backtest mais pas encore actif en production à
   ce stade.
5. **v5 (confluence active en production)** — Ajout de gold-api.com
   comme source de prix temps réel, historique glissant 5h stocké dans
   `state.json`, filtre de confluence pleinement actif avant chaque
   envoi de signal. Limité à XAUUSD à ce stade.
6. **v6 (XAGUSD ajouté, SL/TP en % dynamique)** — **version actuelle**.
   Ajout de XAGUSD en parallèle de XAUUSD, chacun avec son propre suivi
   de prix et sa propre vérification de confluence. SL/TP/breakeven/
   trailing recalculés en % du prix (dynamique) au lieu de pips fixes,
   pour rester valides sur les deux actifs à des échelles de prix très
   différentes.

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

**Gestion de sortie** : Stop Loss fixe (1,5$ / 15 pips sur l'or) +
mécanisme de **breakeven puis trailing stop** :
1. Dès que +2$ de gain latent → SL déplacé au prix d'entrée (perte
   plafonnée au coût du spread)
2. Puis le SL suit à 1$ derrière le meilleur prix atteint, jusqu'au
   Take Profit (15$, ratio R:R 1:10) ou jusqu'à la sortie

**Indicateurs surveillés** : Non-Farm Employment Change (NFP), Core CPI
m/m, Unemployment Rate. Unemployment Claims (hebdomadaire) a été
délibérément exclu — testé et démontré contre-productif seul (PF 1,85).

**Performance validée (backtest)** :

| Marché | Trades (5,1 ans) | Win rate | PF (test 2022-24) | Significativité |
|---|---|---|---|---|
| XAUUSD | 48 | 83,3% | 27,89 | p < 0,33% |
| XAGUSD | 51 | 76,5% | 25,04 | p < 0,33% |

---

## ⚠️ Limitation connue et non résolue

**Le filtre de confluence (tendance des 4h) n'est PAS actif dans le bot
en production.** Il nécessite un flux de prix XAUUSD en temps réel que
ce bot n'a pas encore (infrastructure manquante : ni connexion MT5, ni
API de prix live). Sans ce filtre, le bot envoie un signal dès que la
seule surprise macro dépasse 8% — un edge réel mais partiel (PF attendu
~4-5 sans confluence, contre ~25-28 avec confluence complète).

**Pistes pour résoudre ça** (non implémentées) :
- API de prix gratuite (ex: TwelveData, Alpha Vantage)
- Connexion directe MT5 (nécessite que le bot tourne près du terminal,
  pas compatible avec GitHub Actions en l'état)

De même, le mécanisme de breakeven/trailing est communiqué dans le
message Telegram pour exécution **manuelle** — le bot n'exécute aucun
trade lui-même (pas de connexion broker), il envoie uniquement des
signaux.

---

## Architecture technique

- **Source de données** : flux public ForexFactory
  (`nfs.faireconomy.media/ff_calendar_thisweek.json`) — fournit
  actual/forecast/previous, gratuit, utilisé par la communauté MT4/MT5
  depuis des années. Remplace FRED (qui ne fournit jamais le consensus
  des économistes — voir `BACKTEST_RESULTS.md`, section "Erreur
  corrigée : FRED vs ForexFactory").
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
4. **v4 (confluence macro+tendance, breakeven/trailing)** — **version
   actuelle documentée dans ce README**. PF ~25-28, validée par
   permutation statistique, généralisée à XAGUSD. Filtre de confluence
   pas encore actif en production (limitation ci-dessus).

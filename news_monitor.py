"""
News Trading Monitor — version ForexFactory (100% gratuite)
Exécution unique par lancement (GitHub Actions gère la répétition).

CORRECTION IMPORTANTE (vs version FRED précédente) :
FRED ne fournit JAMAIS les prévisions des économistes (le "forecast"),
seulement les valeurs déjà publiées. La version précédente calculait donc
la "surprise" comme (valeur actuelle vs mois précédent) — une mesure
totalement différente de celle validée par le backtest, qui compare
(valeur actuelle vs consensus des économistes). Cette version utilise le
flux public ForexFactory (utilisé par des milliers de robots MT4/MT5
depuis des années), qui fournit actual/forecast/previous — exactement
la même source que le calendrier historique (scrape.csv) utilisé pour
tout le backtest.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news-monitor")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FF_CALENDAR_URL  = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STATE_FILE       = "state.json"
CACHE_MIN_INTERVAL_MINUTES = 30  # ForexFactory limite les requetes — on met en cache

# Evenements retenus suite au backtest complet (5.1 ans, XAUUSD M1, 2019-2024,
# config confluence macro+tendance + breakeven/trailing). PF~26 en test,
# valide par test de permutation (0/300 tirages aleatoires egalent ce PF).
# Les libelles doivent correspondre exactement a ceux du flux ForexFactory.
TARGET_EVENTS = {
    "Non-Farm Employment Change": {"usd_positive_if_higher": True},
    "Core CPI m/m":               {"usd_positive_if_higher": True},
    "Unemployment Rate":          {"usd_positive_if_higher": False},
}

MIN_SURPRISE_PCT = 8.0  # seuil valide par le backtest (config "Large")

# Le backtest multi-marches (session precedente) a confirme que l'edge
# n'existe PAS sur les paires de devises classiques (EURUSD/GBPUSD/USDJPY),
# mais SE GENERALISE aux deux metaux precieux testes : XAUUSD (PF test
# 27.89) ET XAGUSD (PF test 25.04), tous deux valides par permutation
# statistique (p<0.33%). Seuils identiques en % du prix pour les deux
# actifs (valide par sanity-check : XAUUSD en % redonne le meme PF que
# XAUUSD en dollars absolus).
PAIR_DIRECTION = {
    "XAUUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
    "XAGUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
}
PAIRS_TO_TRADE = ["XAUUSD", "XAGUSD"]

# Symbole utilise par gold-api.com pour chaque paire (gratuit, sans cle,
# sans limite de requetes sur l'endpoint prix temps reel).
GOLD_API_SYMBOL = {
    "XAUUSD": "XAU",
    "XAGUSD": "XAG",
}

# Seuils valides par le backtest complet, exprimes en % du prix (pas en
# dollars fixes) pour etre applicables aux deux actifs a des echelles de
# prix tres differentes (or ~1888$, argent ~23$ sur la periode de
# reference). PF test ~25-28 selon l'actif, win rate 76.5%-83.3%,
# p<0.33% (permutation) sur les deux.
SL_PCT = 1.5 / 1888.31
TP_PCT = 15.0 / 1888.31
BREAKEVEN_TRIGGER_PCT = 2.0 / 1888.31
TRAIL_DISTANCE_PCT = 1.0 / 1888.31
MIN_TREND_PCT = 5.0 / 1888.31

PRICE_HISTORY_MAX_HOURS = 5  # marge au-dela des 4h necessaires au filtre de confluence


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_current_price(pair: str) -> float | None:
    """Recupere le prix en temps reel via gold-api.com (gratuit, sans
    cle, sans limite de requetes sur cet endpoint), pour XAUUSD ou XAGUSD."""
    symbol = GOLD_API_SYMBOL[pair]
    try:
        r = requests.get(f"https://api.gold-api.com/price/{symbol}", timeout=10)
        r.raise_for_status()
        data = r.json()
        price = data.get("price")
        return float(price) if price is not None else None
    except Exception as e:
        log.error(f"Erreur gold-api.com ({pair}) : {e}")
        return None


def record_price_snapshot(state: dict):
    """Enregistre le prix actuel de chaque paire suivie, et purge les
    entrees de plus de PRICE_HISTORY_MAX_HOURS."""
    now = datetime.now(timezone.utc)
    all_history = state.setdefault("price_history", {})

    for pair in PAIRS_TO_TRADE:
        price = fetch_current_price(pair)
        if price is None:
            log.warning(f"Impossible de recuperer le prix {pair} — snapshot ignore")
            continue

        history = all_history.setdefault(pair, [])
        history.append({"t": now.isoformat(), "price": price})

        cutoff = now - timedelta(hours=PRICE_HISTORY_MAX_HOURS)
        all_history[pair] = [h for h in history if datetime.fromisoformat(h["t"]) >= cutoff]
        log.info(f"Snapshot {pair} enregistre : {price} ({len(all_history[pair])} points en historique)")


def check_trend_confluence(pair: str, direction: str, state: dict):
    """Verifie que la tendance des 4h precedentes (pour CETTE paire) est
    alignee avec la direction predite, avec une force suffisante
    (>= MIN_TREND_PCT). Renvoie (True/False/None, pre_move_pct).
    None = donnees insuffisantes pour trancher."""
    history = state.get("price_history", {}).get(pair, [])
    if len(history) < 2:
        return None, None

    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=4)
    history_sorted = sorted(history, key=lambda h: h["t"])

    oldest = datetime.fromisoformat(history_sorted[0]["t"])
    if oldest > target + timedelta(minutes=20):
        # pas encore 4h d'historique accumule (ex: bot vient de redemarrer)
        return None, None

    ref_point = min(history_sorted, key=lambda h: abs(datetime.fromisoformat(h["t"]) - target))
    price_4h_ago = ref_point["price"]
    price_now = history_sorted[-1]["price"]

    if price_4h_ago == 0:
        return None, None

    pre_move_pct = (price_now - price_4h_ago) / price_4h_ago
    aligned = (pre_move_pct > 0) if direction == "BUY" else (pre_move_pct < 0)
    strong_enough = abs(pre_move_pct) >= MIN_TREND_PCT

    return (aligned and strong_enough), pre_move_pct


def fetch_calendar(state: dict) -> list:
    """Recupere le calendrier ForexFactory, avec cache pour respecter
    la limite de requetes (max 2 / 5 min sur ce flux public partage)."""
    now = datetime.now(timezone.utc)
    last_fetch = state.get("last_calendar_fetch")
    cached = state.get("calendar_cache")

    if last_fetch and cached:
        last_dt = datetime.fromisoformat(last_fetch)
        if (now - last_dt) < timedelta(minutes=CACHE_MIN_INTERVAL_MINUTES):
            log.info("Calendrier : utilisation du cache (dernier fetch < %d min)", CACHE_MIN_INTERVAL_MINUTES)
            return cached

    try:
        r = requests.get(FF_CALENDAR_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        events = r.json()
        state["last_calendar_fetch"] = now.isoformat()
        state["calendar_cache"] = events
        log.info("Calendrier ForexFactory recupere : %d evenements", len(events))
        return events
    except Exception as e:
        log.error(f"Erreur ForexFactory calendar : {e}")
        return cached or []


def calculate_signal(event: dict):
    """Calcule la surprise = actual vs forecast (PAS vs previous),
    exactement comme dans le backtest valide."""
    title = event.get("title", "")
    if title not in TARGET_EVENTS:
        return None
    if event.get("country") != "USD":
        return None

    actual_raw = event.get("actual")
    forecast_raw = event.get("forecast")
    if actual_raw in (None, "", "N/A") or forecast_raw in (None, "", "N/A"):
        return None  # pas encore publie, ou pas de consensus disponible

    def parse_num(v):
        if isinstance(v, str):
            v = v.replace("%", "").replace("K", "").replace(",", "").strip()
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    actual = parse_num(actual_raw)
    forecast = parse_num(forecast_raw)
    if actual is None or forecast is None or forecast == 0:
        return None

    pct = abs((actual - forecast) / forecast * 100)
    if pct < MIN_SURPRISE_PCT:
        return None

    usd_positive = (actual > forecast) == TARGET_EVENTS[title]["usd_positive_if_higher"]

    return {
        "title": title,
        "date": event.get("date", ""),
        "actual": actual_raw,
        "forecast": forecast_raw,
        "previous": event.get("previous", ""),
        "pct": pct,
        "usd_positive": usd_positive,
    }


def format_telegram_message(signal: dict, pair_results: dict) -> str:
    """pair_results : { "XAUUSD": (confluence_ok, pre_move_pct, current_price), ... }
    Seules les paires avec confluence_ok True ou None (non verifiable)
    sont incluses — celles a False sont deja filtrees en amont."""
    usd_dir = "FORT 📈" if signal["usd_positive"] else "FAIBLE 📉"

    lines = [
        "🚨 <b>SIGNAL NEWS TRADING</b>",
        "",
        f"📊 <b>{signal['title'].upper()}</b> ({signal['date']})",
        f"Publié : <b>{signal['actual']}</b>",
        f"Attendu (consensus) : {signal['forecast']}",
        f"Mois précédent : {signal['previous']}",
        f"Surprise vs consensus : <b>{signal['pct']:.1f}%</b> (seuil validé : {MIN_SURPRISE_PCT}%)",
        f"Dollar : <b>{usd_dir}</b>",
        "",
        "─────────────────────",
    ]

    for pair, (confluence_ok, pre_move_pct, current_price) in pair_results.items():
        direction = PAIR_DIRECTION[pair]["usd_strong" if signal["usd_positive"] else "usd_weak"]
        emoji = "🟢" if direction == "BUY" else "🔴"

        if current_price:
            sl_amount = current_price * SL_PCT
            tp_amount = current_price * TP_PCT
            be_amount = current_price * BREAKEVEN_TRIGGER_PCT
            trail_amount = current_price * TRAIL_DISTANCE_PCT
            lines.append(
                f"{emoji} <b>{pair}</b> → {direction} | SL {sl_amount:.3f}$ | TP {tp_amount:.3f}$ | R:R 1:10"
            )
            lines.append(
                f"   Breakeven a +{be_amount:.3f}$, trailing a {trail_amount:.3f}$ derriere le meilleur prix"
            )
        else:
            lines.append(f"{emoji} <b>{pair}</b> → {direction} | (prix indisponible, verifier manuellement)")

        if confluence_ok is None:
            lines.append("   ⚠️ Confluence non verifiable (historique insuffisant) — edge plus faible attendu")
        else:
            lines.append(f"   ✅ Confluence confirmee (tendance 4h {pre_move_pct*100:+.2f}%)")

    lines += [
        "─────────────────────",
        "",
        "⚠️ <b>EXECUTION — REGLE VALIDEE PAR BACKTEST</b>",
        "",
        "✅ ENTRER IMMEDIATEMENT, sans attendre de confirmation.",
        "   Un delai, meme d'1 min, detruit fortement l'edge.",
        "",
        "🎯 SORTIE — Breakeven puis trailing (valide, PF x2 vs SL/TP fixe) :",
        "   1. Des que le gain latent atteint le seuil breakeven ci-dessus,",
        "      deplace le SL au prix d'entree (perte plafonnee au spread).",
        "   2. Puis fais suivre le SL derriere le meilleur prix atteint",
        "      (distance de trailing indiquee ci-dessus), jusqu'au TP.",
        "",
        "🎯 Le spread/slippage est plus eleve a cet instant precis",
        "   (x2 a x3 la normale, jusqu'a x8 sur CPI/NFP extremes)",
        "   — c'est le cout normal de l'edge, pas un signal d'alerte.",
        "",
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC — Source : ForexFactory (consensus) + gold-api.com (prix)",
    ]
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram non configuré — affichage console uniquement")
        print(message)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
        log.info("Message Telegram envoyé avec succès")
        return True
    except Exception as e:
        log.error(f"Erreur Telegram : {e}")
        return False


def check_heartbeat(state: dict):
    """Envoie un message hebdomadaire pour confirmer que le bot est actif."""
    last_heartbeat = state.get("last_heartbeat")
    now = datetime.now(timezone.utc)

    if last_heartbeat:
        last_dt = datetime.fromisoformat(last_heartbeat)
        days_since = (now - last_dt).days
        if days_since < 7:
            return

    msg = (
        "💓 <b>News Monitor Bot — toujours actif</b>\n\n"
        f"Dernière vérification : {now.strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"Indicateurs surveillés : {len(TARGET_EVENTS)} (NFP, Core CPI, Chômage)\n"
        "Aucune action requise — ceci est juste une confirmation "
        "que le système tourne normalement."
    )
    send_telegram(msg)
    state["last_heartbeat"] = now.isoformat()


def run_once():
    state = load_state()
    check_heartbeat(state)

    missing = [n for n, v in [
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ] if not v]
    if missing:
        log.error(f"Variables manquantes : {', '.join(missing)} — arrêt.")
        save_state(state)
        return

    # Snapshot de prix a CHAQUE execution (independamment des news), pour
    # accumuler l'historique necessaire au filtre de confluence 4h.
    record_price_snapshot(state)

    events = fetch_calendar(state)
    processed = state.setdefault("processed_events", [])

    for event in events:
        title = event.get("title", "")
        date = event.get("date", "")
        event_key = f"{title}|{date}"
        if event_key in processed:
            continue

        signal = calculate_signal(event)
        if signal is None:
            if event.get("actual") not in (None, "", "N/A"):
                processed.append(event_key)
            continue

        processed.append(event_key)

        pair_results = {}
        for pair in PAIRS_TO_TRADE:
            direction = PAIR_DIRECTION[pair]["usd_strong" if signal["usd_positive"] else "usd_weak"]
            confluence_ok, pre_move_pct = check_trend_confluence(pair, direction, state)

            if confluence_ok is False:
                pm = pre_move_pct * 100 if pre_move_pct else 0
                log.info(
                    f"{pair} — signal {signal['title']} ({signal['pct']:.1f}%) REJETE par le "
                    f"filtre de confluence (tendance 4h={pm:+.2f}%, non alignee ou trop faible)."
                )
                continue  # cette paire est exclue, mais les autres peuvent quand meme s'afficher

            history = state.get("price_history", {}).get(pair, [])
            current_price = history[-1]["price"] if history else None
            pair_results[pair] = (confluence_ok, pre_move_pct, current_price)

        if not pair_results:
            log.info(f"Aucune paire n'a passe le filtre de confluence pour {signal['title']} — pas d'envoi.")
            continue

        log.info(f"Nouveau signal : {signal['title']} | surprise {signal['pct']:.1f}% | paires={list(pair_results.keys())}")
        send_telegram(format_telegram_message(signal, pair_results))

    state["processed_events"] = processed[-200:]
    save_state(state)


if __name__ == "__main__":
    run_once()

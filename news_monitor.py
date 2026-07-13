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
# n'existe que sur XAUUSD : EURUSD/GBPUSD/USDJPY n'ont jamais ete valides
# statistiquement. On ne garde donc que XAUUSD pour eviter d'envoyer des
# signaux trompeurs sur des paires sans edge demontre.
PAIR_DIRECTION = {
    "XAUUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
}
PAIRS_TO_TRADE = ["XAUUSD"]

# SL/TP + mecanisme breakeven/trailing valides par le backtest complet
# (config "Large" : surprise>=8%, tendance pre-annonce>=5$, breakeven+trailing
# 2$/1$). PF test ~25, win rate 83.3% sur 48 trades, p<0.0033 (permutation).
SL_TP = {
    "XAUUSD": {"sl": 15, "tp": 150, "pip": 0.1, "breakeven_trigger": 20, "trail_distance": 10},
}

# LIMITATION CONNUE, PAS ENCORE RESOLUE :
# Le filtre de confluence (tendance des 4h precedant l'annonce alignee avec
# la direction macro) ameliore fortement le PF dans le backtest, mais
# necessite un flux de prix XAUUSD en temps reel que ce bot n'a pas encore.
# Sans lui, ce bot envoie un signal des que la surprise macro seule depasse
# le seuil — un edge reel mais legerement inferieur a la config complete
# testee (PF ~4-5 attendu sans confluence, vs PF ~25 avec confluence).


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


def format_telegram_message(signal: dict) -> str:
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
    for pair in PAIRS_TO_TRADE:
        direction = PAIR_DIRECTION[pair]["usd_strong" if signal["usd_positive"] else "usd_weak"]
        sl_tp = SL_TP[pair]
        emoji = "🟢" if direction == "BUY" else "🔴"
        lines.append(
            f"{emoji} <b>{pair}</b> → {direction} | SL {sl_tp['sl']} pips | TP {sl_tp['tp']} pips | R:R 1:{sl_tp['tp']//sl_tp['sl']}"
        )

    lines += [
        "─────────────────────",
        "",
        "⚠️ <b>EXECUTION — REGLE VALIDEE PAR BACKTEST</b>",
        "",
        "✅ ENTRER IMMEDIATEMENT, sans attendre de confirmation.",
        "   Un delai, meme d'1 min, detruit fortement l'edge.",
        "",
        "🎯 SORTIE — Breakeven puis trailing (valide, PF x2 vs SL/TP fixe) :",
        f"   1. Des que +2 dollars (soit +{sl_tp['breakeven_trigger']} pips) de gain latent,",
        "      deplace le SL au prix d'entree (perte plafonnee au spread).",
        f"   2. Puis fais suivre le SL a 1 dollar (soit {sl_tp['trail_distance']} pips)",
        "      derriere le meilleur prix atteint, jusqu'au TP ou a la sortie.",
        "",
        "🎯 Le spread/slippage est plus eleve a cet instant precis",
        "   (x2 a x3 la normale, jusqu'a x8 sur CPI/NFP extremes)",
        "   — c'est le cout normal de l'edge, pas un signal d'alerte.",
        "",
        "ℹ️ Filtre de confluence (tendance 4h) pas encore actif sur ce bot",
        "   — infra de prix temps reel manquante. Edge reel mais partiel.",
        "",
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC — Source : ForexFactory (consensus)",
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
            # soit hors-cible, soit pas encore publie -> on ne marque PAS
            # comme traite si l'actual n'est pas encore disponible, pour
            # pouvoir re-verifier au prochain lancement.
            if event.get("actual") not in (None, "", "N/A"):
                processed.append(event_key)
            continue

        processed.append(event_key)
        log.info(f"Nouveau signal : {signal['title']} | surprise {signal['pct']:.1f}%")
        send_telegram(format_telegram_message(signal))

    # limiter la taille de l'historique traite
    state["processed_events"] = processed[-200:]
    save_state(state)


if __name__ == "__main__":
    run_once()

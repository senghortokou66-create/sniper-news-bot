"""
News Trading Monitor — Architecture automatisée complète
=========================================================
Surveille le calendrier économique Finnhub en temps réel,
analyse les annonces dès qu'elles sortent, et envoie un
signal de trading complet sur Telegram en quelques secondes.

COMPOSANTS :
  1. Finnhub API  → calendrier économique (gratuit, 60 appels/min)
  2. Ce serveur   → analyse la surprise + génère le signal
  3. Telegram Bot → notification instantanée sur iPhone
  4. (optionnel)  → webhook TradingView pour affichage visuel

CONFIGURATION (variables d'environnement) :
  FINNHUB_API_KEY     → clé gratuite sur finnhub.io
  TELEGRAM_BOT_TOKEN  → créé via @BotFather sur Telegram
  TELEGRAM_CHAT_ID    → ton ID Telegram (via @userinfobot)

ÉTAPES D'INSTALLATION :
  1. Inscris-toi sur https://finnhub.io → copie ta clé API
  2. Ouvre Telegram → cherche @BotFather → /newbot → copie le token
  3. Cherche @userinfobot sur Telegram → copie ton Chat ID
  4. Déploie ce fichier sur Render.com (free tier)
  5. Ajoute les 3 variables d'environnement dans Render
  6. C'est tout — le système tourne 24/7 automatiquement

COÛT TOTAL : 0$ (Finnhub gratuit + Render gratuit + Telegram gratuit)
"""

import os
import time
import json
import logging
import requests
from datetime import datetime, date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("news-monitor")

FINNHUB_API_KEY  = os.environ.get("FINNHUB_API_KEY", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FINNHUB_BASE     = "https://finnhub.io/api/v1"

# ==========================================
# ANNONCES À SURVEILLER (impact fort USD)
# ==========================================
HIGH_IMPACT_KEYWORDS = [
    "nonfarm payroll", "nfp",
    "consumer price index", "cpi",
    "federal funds rate", "fomc", "fed",
    "gdp", "gross domestic product",
    "retail sales",
    "ism manufacturing", "ism services",
    "unemployment", "jobless claims",
    "pce", "personal consumption",
    "producer price", "ppi",
    "trade balance",
]

# Impact sur EURUSD selon le sens de la surprise USD
# True  = USD fort → EURUSD baisse → SELL EURUSD
# False = USD faible → EURUSD monte → BUY EURUSD
PAIR_DIRECTION = {
    "EURUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
    "GBPUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
    "USDJPY": {"usd_strong": "BUY",  "usd_weak": "SELL"},
    "XAUUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
}

# Paires à inclure dans chaque signal
PAIRS_TO_TRADE = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

# SL et TP en pips par paire
SL_TP = {
    "EURUSD": {"sl": 25, "tp": 75,  "pip": 0.0001},
    "GBPUSD": {"sl": 25, "tp": 75,  "pip": 0.0001},
    "USDJPY": {"sl": 25, "tp": 75,  "pip": 0.01},
    "XAUUSD": {"sl": 30, "tp": 100, "pip": 0.1},
}


def get_economic_calendar() -> list:
    """Récupère les annonces économiques du jour depuis Finnhub."""
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    url = (f"{FINNHUB_BASE}/calendar/economic"
           f"?from={today}&to={tomorrow}&token={FINNHUB_API_KEY}")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("economicCalendar", [])
    except Exception as e:
        log.error(f"Erreur Finnhub : {e}")
        return []


def is_high_impact(event: dict) -> bool:
    """Retourne True si l'annonce est à fort impact USD."""
    event_name = (event.get("event") or "").lower()
    country    = (event.get("country") or "").upper()
    impact     = (event.get("impact") or "").lower()

    if country != "US":
        return False
    if impact in ("high", "3"):
        return True
    return any(kw in event_name for kw in HIGH_IMPACT_KEYWORDS)


def calculate_signal(event: dict) -> dict | None:
    """
    Calcule la force et la direction du signal à partir de la surprise.
    Retourne None si la surprise est trop faible pour trader.
    """
    actual   = event.get("actual")
    estimate = event.get("estimate")
    prev     = event.get("prev")

    if actual is None:
        return None  # Annonce pas encore sortie

    # Calcul de la surprise
    reference = estimate if estimate is not None else prev
    if reference is None or reference == 0:
        return None

    diff = actual - reference
    pct  = abs(diff / reference * 100)

    # Seuil minimum de surprise pour trader (5%)
    if pct < 5:
        log.info(f"Surprise trop faible ({pct:.1f}%) — pas de signal")
        return None

    # Force du signal (1-5 étoiles)
    if pct < 10:   strength = 2
    elif pct < 20: strength = 3
    elif pct < 40: strength = 4
    else:          strength = 5

    usd_positive = diff > 0  # surprise positive pour le dollar

    return {
        "event":        event.get("event", "Annonce inconnue"),
        "actual":       actual,
        "estimate":     estimate,
        "diff":         diff,
        "pct":          pct,
        "usd_positive": usd_positive,
        "strength":     strength,
    }


def format_telegram_message(signal: dict) -> str:
    """Formate le message Telegram avec tous les détails du trade
    et les règles anti-manipulation intégrées."""
    stars    = "⭐" * signal["strength"] + "☆" * (5 - signal["strength"])
    surprise = f"{'+' if signal['diff'] > 0 else ''}{signal['diff']:.2f}"
    pct_str  = f"{signal['pct']:.1f}%"
    usd_dir  = "FORT 📈" if signal["usd_positive"] else "FAIBLE 📉"

    lines = [
        f"🚨 <b>SIGNAL NEWS TRADING</b>",
        f"",
        f"📊 <b>{signal['event'].upper()}</b>",
        f"Résultat réel  : <b>{signal['actual']}</b>",
        f"Prévision      : {signal['estimate']}",
        f"Surprise       : <b>{surprise}</b> ({pct_str})",
        f"Dollar         : <b>{usd_dir}</b>",
        f"Force du signal: {stars} ({signal['strength']}/5)",
        f"",
        f"─────────────────────",
    ]

    # Niveaux par paire
    for pair in PAIRS_TO_TRADE:
        direction = PAIR_DIRECTION[pair]["usd_strong" if signal["usd_positive"] else "usd_weak"]
        sl_tp     = SL_TP[pair]
        pip       = sl_tp["pip"]
        sl_pips   = sl_tp["sl"]
        tp_pips   = sl_tp["tp"]
        emoji = "🟢" if direction == "BUY" else "🔴"
        lines.append(
            f"{emoji} <b>{pair}</b>  →  {direction}"
            f"  |  SL {sl_pips} pips  |  TP {tp_pips} pips  |  R:R 1:{tp_pips // sl_pips}"
        )

    # ==========================================
    # RÈGLES ANTI-MANIPULATION (FAKE SPIKE)
    # ==========================================
    expected_dir = "BAISSER" if signal["usd_positive"] else "MONTER"
    wrong_dir    = "MONTE"   if signal["usd_positive"] else "BAISSE"
    candle_color = "ROUGE"   if signal["usd_positive"] else "VERTE"

    lines += [
        f"─────────────────────",
        f"",
        f"⚠️ <b>RÈGLES ANTI-MANIPULATION</b>",
        f"",
        f"🎭 <b>Fake Spike probable !</b> Le marché peut d'abord",
        f"   {wrong_dir} pour chasser les stop-loss avant",
        f"   d'aller dans le bon sens ({expected_dir}).",
        f"",
        f"✅ <b>ENTRER seulement si :</b>",
        f"   1️⃣ La bougie 1min clôture {candle_color} (confirmation directionnelle)",
        f"   2️⃣ Le mouvement est &lt; 50 pips du prix pré-annonce",
        f"      (si &gt; 50 pips → trop tard, attendre retracement)",
        f"   3️⃣ L'entrée se fait dans les 3 premières minutes",
        f"      (après 3 min sans signal clair → annuler)",
        f"",
        f"❌ <b>NE PAS ENTRER si :</b>",
        f"   • La première bougie 1min va dans le mauvais sens",
        f"   • Le spread est anormalement large (&gt; 3× la normale)",
        f"   • Deux mouvements contradictoires en &lt; 30 secondes",
        f"",
        f"🕐 {datetime.utcnow().strftime('%H:%M:%S')} UTC — Signal valide 3 minutes",
    ]

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    """Envoie un message Telegram et retourne True si succès."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram non configuré — affichage console uniquement")
        print("\n" + "="*50)
        print(message)
        print("="*50 + "\n")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
        log.info("Message Telegram envoyé avec succès")
        return True
    except Exception as e:
        log.error(f"Erreur Telegram : {e}")
        return False


def send_startup_message():
    """Envoie un message de confirmation au démarrage du serveur."""
    msg = (
        "✅ <b>News Trading Monitor démarré</b>\n\n"
        "Je surveille les annonces économiques US à fort impact :\n"
        "📌 NFP — CPI — FOMC — GDP — ISM — Retail Sales\n\n"
        "Tu recevras un signal ici dès qu'une annonce sort "
        "avec une surprise significative (&gt;5%).\n\n"
        f"🕐 Démarré à {datetime.utcnow().strftime('%H:%M:%S')} UTC"
    )
    send_telegram(msg)


def monitor():
    """
    Boucle principale de surveillance.
    Interroge Finnhub toutes les 30 secondes,
    détecte les nouvelles annonces, génère et envoie les signaux.
    """
    processed_ids = set()  # Évite d'envoyer le même signal deux fois
    log.info("Démarrage de la surveillance du calendrier économique...")
    send_startup_message()

    while True:
        events = get_economic_calendar()

        for event in events:
            # Identifiant unique de l'annonce
            event_id = f"{event.get('event', '')}_{event.get('time', '')}"

            if event_id in processed_ids:
                continue

            if not is_high_impact(event):
                continue

            signal = calculate_signal(event)

            if signal:
                processed_ids.add(event_id)
                log.info(f"Signal détecté : {signal['event']} | "
                         f"Surprise {signal['pct']:.1f}% | "
                         f"Force {signal['strength']}/5")
                message = format_telegram_message(signal)
                send_telegram(message)

        # Polling toutes les 30 secondes (bien dans la limite de 60/min de Finnhub)
        time.sleep(30)


if __name__ == "__main__":
    missing = [n for n, v in [
        ("FINNHUB_API_KEY",  FINNHUB_API_KEY),
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID",   TELEGRAM_CHAT_ID),
    ] if not v]

    if missing:
        log.warning(f"Variables manquantes : {', '.join(missing)}")
        log.warning("Le serveur démarre mais certaines fonctions seront limitées.")

    monitor()

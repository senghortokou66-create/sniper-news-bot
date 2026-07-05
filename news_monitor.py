"""
News Trading Monitor — version FRED (100% gratuite)
Exécution unique par lancement (GitHub Actions gère la répétition).
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news-monitor")

FRED_API_KEY     = os.environ.get("FRED_API_KEY", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FRED_BASE        = "https://api.stlouisfed.org/fred/series/observations"
STATE_FILE       = "state.json"

SERIES = {
    "PAYEMS":   {"label": "Nonfarm Payrolls (NFP)", "unit": "K emplois"},
    "CPIAUCSL": {"label": "CPI (Inflation)", "unit": "indice"},
    "UNRATE":   {"label": "Taux de chômage", "unit": "%"},
    "ICSA":     {"label": "Jobless Claims (hebdo)", "unit": "demandes"},
    "RSAFS":    {"label": "Ventes au détail", "unit": "M$"},
    "PPIACO":   {"label": "PPI (Prix producteur)", "unit": "indice"},
    "PCEPILFE": {"label": "Core PCE", "unit": "indice"},
}

PAIR_DIRECTION = {
    "EURUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
    "GBPUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
    "USDJPY": {"usd_strong": "BUY",  "usd_weak": "SELL"},
    "XAUUSD": {"usd_strong": "SELL", "usd_weak": "BUY"},
}
PAIRS_TO_TRADE = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
SL_TP = {
    "EURUSD": {"sl": 25, "tp": 75,  "pip": 0.0001},
    "GBPUSD": {"sl": 25, "tp": 75,  "pip": 0.0001},
    "USDJPY": {"sl": 25, "tp": 75,  "pip": 0.01},
    "XAUUSD": {"sl": 30, "tp": 100, "pip": 0.1},
}


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


def fetch_latest_observations(series_id: str) -> list:
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 2,
    }
    try:
        r = requests.get(FRED_BASE, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("observations", [])
    except Exception as e:
        log.error(f"Erreur FRED ({series_id}) : {e}")
        return []


def calculate_signal(series_id: str, obs: list):
    if len(obs) < 2:
        return None
    latest, previous = obs[0], obs[1]
    try:
        actual = float(latest["value"])
        prev = float(previous["value"])
    except (ValueError, KeyError):
        return None
    if prev == 0:
        return None

    diff = actual - prev
    pct = abs(diff / prev * 100)
    if pct < 0.5:
        return None

    if pct < 1:    strength = 2
    elif pct < 2:  strength = 3
    elif pct < 4:  strength = 4
    else:          strength = 5

    usd_positive = diff > 0
    if series_id in ("UNRATE", "ICSA"):
        usd_positive = diff < 0

    return {
        "series_id": series_id,
        "label": SERIES[series_id]["label"],
        "unit": SERIES[series_id]["unit"],
        "date": latest["date"],
        "actual": actual,
        "previous": prev,
        "diff": diff,
        "pct": pct,
        "usd_positive": usd_positive,
        "strength": strength,
    }


def format_telegram_message(signal: dict) -> str:
    stars = "⭐" * signal["strength"] + "☆" * (5 - signal["strength"])
    surprise = f"{'+' if signal['diff'] > 0 else ''}{signal['diff']:.2f}"
    usd_dir = "FORT 📈" if signal["usd_positive"] else "FAIBLE 📉"

    lines = [
        "🚨 <b>SIGNAL NEWS TRADING</b>",
        "",
        f"📊 <b>{signal['label'].upper()}</b> ({signal['date']})",
        f"Valeur actuelle : <b>{signal['actual']}</b> {signal['unit']}",
        f"Valeur précédente : {signal['previous']} {signal['unit']}",
        f"Variation : <b>{surprise}</b> ({signal['pct']:.1f}%)",
        f"Dollar : <b>{usd_dir}</b>",
        f"Force du signal : {stars} ({signal['strength']}/5)",
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

    expected_dir = "BAISSER" if signal["usd_positive"] else "MONTER"
    wrong_dir = "MONTE" if signal["usd_positive"] else "BAISSE"
    candle_color = "ROUGE" if signal["usd_positive"] else "VERTE"

    lines += [
        "─────────────────────",
        "",
        "⚠️ <b>RÈGLES ANTI-MANIPULATION</b>",
        "",
        f"🎭 Fake Spike probable : le marché peut d'abord {wrong_dir}",
        f"   avant d'aller dans le bon sens ({expected_dir}).",
        "",
        "✅ ENTRER seulement si :",
        f"   1️⃣ La bougie 1min clôture {candle_color}",
        "   2️⃣ Mouvement < 50 pips du prix pré-annonce",
        "   3️⃣ Entrée dans les 3 premières minutes",
        "",
        "❌ NE PAS ENTRER si :",
        "   • Première bougie dans le mauvais sens",
        "   • Spread anormalement large (> 3x la normale)",
        "",
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC — Donnée FRED (vs mois précédent)",
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
        f"Indicateurs surveillés : {len(SERIES)}\n"
        "Aucune action requise — ceci est juste une confirmation "
        "que le système tourne normalement."
    )
    send_telegram(msg)
    state["last_heartbeat"] = now.isoformat()


def run_once():
    state = load_state()
    check_heartbeat(state)

    missing = [n for n, v in [
        ("FRED_API_KEY", FRED_API_KEY),
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ] if not v]
    if missing:
        log.error(f"Variables manquantes : {', '.join(missing)} — arrêt.")
        save_state(state)
        return

    for series_id in SERIES:
        obs = fetch_latest_observations(series_id)
        if not obs:
            continue
        latest_date = obs[0]["date"]
        if latest_date == state.get(series_id):
            log.info(f"{series_id} : pas de nouvelle donnée")
            continue

        signal = calculate_signal(series_id, obs)
        state[series_id] = latest_date

        if signal:
            log.info(f"Nouveau signal : {signal['label']} | {signal['pct']:.1f}%")
            send_telegram(format_telegram_message(signal))
        else:
            log.info(f"{series_id} : nouvelle donnée, variation trop faible")

    save_state(state)


if __name__ == "__main__":
    run_once()

import aiohttp
import time
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ======================
# 🔑 НАСТРОЙКИ
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_SPORTS_KEY = os.getenv("RAPID_API_KEY")   # используем тот же env
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID")) if os.getenv("YOUR_TELEGRAM_ID") else 0

LIVE_CHECK_INTERVAL = 864
MATCHES_PER_PAGE = 5
DAILY_LIMIT = 100

api_request_count = 0

ALL_FOOTBALL_LEAGUES = [
    {"id": 39, "name": "АПЛ (Англия)"},
    {"id": 140, "name": "Ла Лига (Испания)"},
    {"id": 135, "name": "Серия А (Италия)"},
    {"id": 78, "name": "Бундеслига (Германия)"},
    {"id": 61, "name": "Лига 1 (Франция)"},
    {"id": 2, "name": "Лига Чемпионов"},
]

ALL_HOCKEY_LEAGUES = [
    {"id": 57, "name": "NHL (США/Канада)"},
    {"id": 105, "name": "КХЛ (Россия)"},
]

user_data = {
    "selected_football": [39],
    "selected_hockey": [57],
    "monitoring_match_id": None,
    "last_score": {}
}

# ======================
# 🌐 ПРЯМОЙ API SPORTS IO
# ======================

BASE_URL = "https://v3.football.api-sports.io"

def get_headers():
    return {
        "x-apisports-key": API_SPORTS_KEY
    }

async def make_api_request(endpoint, params=None):
    global api_request_count

    api_request_count += 1
    logging.info(f"📡 Запрос #{api_request_count}/{DAILY_LIMIT}")

    url = f"{BASE_URL}{endpoint}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=get_headers(),
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:

                if response.status == 200:
                    return await response.json()

                text = await response.text()
                logging.error(f"API error {response.status}: {text}")
                return None

    except Exception as e:
        logging.error(f"Ошибка запроса: {e}")
        return None


# ======================
# 📅 ПОЛУЧЕНИЕ МАТЧЕЙ
# ======================

async def get_today_matches():
    matches = []
    today = time.strftime("%Y-%m-%d")

    for league_id in user_data["selected_football"]:
        data = await make_api_request("/fixtures", {
            "date": today,
            "league": league_id,
            "timezone": "Europe/Moscow"
        })

        if data and "response" in data:
            for m in data["response"]:
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "time": m["fixture"]["date"][11:16],
                })

    return matches


async def get_live_matches():
    matches = []

    for league_id in user_data["selected_football"]:
        data = await make_api_request("/fixtures", {
            "live": "all",
            "league": league_id
        })

        if data and "response" in data:
            for m in data["response"]:
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "home_goals": m["goals"]["home"] or 0,
                    "away_goals": m["goals"]["away"] or 0,
                    "elapsed": m["fixture"]["status"]["elapsed"] or "?",
                })

    return matches


async def get_match_details(match_id):
    data = await make_api_request("/fixtures", {"id": match_id})

    if data and data.get("response"):
        m = data["response"][0]
        return {
            "home": m["teams"]["home"]["name"],
            "away": m["teams"]["away"]["name"],
            "home_goals": m["goals"]["home"] or 0,
            "away_goals": m["goals"]["away"] or 0,
            "status": m["fixture"]["status"]["short"],
            "league": m["league"]["name"]
        }

    return None


# ======================
# 🤖 TELEGRAM
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Матчи на сегодня", callback_data='today_all')],
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
    ]

    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_today_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    matches = await get_today_matches()

    if not matches:
        await query.edit_message_text("Сегодня нет матчей.")
        return

    text = "📅 Матчи на сегодня:\n\n"

    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        text += f"{i}. {m['league']}\n⏰ {m['time']} {m['home']} – {m['away']}\n\n"

    await query.edit_message_text(text)


async def show_live_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    matches = await get_live_matches()

    if not matches:
        await query.edit_message_text("Нет live матчей.")
        return

    text = "🔴 Live:\n\n"

    for m in matches[:MATCHES_PER_PAGE]:
        score = f"{m['home_goals']}:{m['away_goals']}"
        text += f"{m['league']}\n{m['home']} {score} {m['away']}\n\n"

    await query.edit_message_text(text)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "today_all":
        await show_today_matches(update, context)

    elif data == "live":
        await show_live_matches(update, context)


# ======================
# 🚀 ЗАПУСК
# ======================

def main():
    logging.basicConfig(level=logging.INFO)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
        

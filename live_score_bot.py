import aiohttp
import time
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ======================
# НАСТРОЙКИ
# ======================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")

user_data = {
    "selected_football": [78],
    "selected_hockey": [57, 35, 36, 37],   # NHL, KHL, VHL, MHL
    "monitoring": {
        "match_id": None,
        "sport": None,
        "last_score": {"home": 0, "away": 0}
    },
    "check_interval": 30
}

MATCHES_PER_PAGE = 5

# ======================
# API ЗАПРОСЫ
# ======================

async def fetch_hockey_today():
    headers = {
        "x-apisports-key": API_SPORTS_KEY
    }

    url = "https://v1.hockey.api-sports.io/games?date=today"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:

                data = await resp.json()
                return data.get("response", [])

    except Exception as e:
        logging.error("Hockey API error: %s", e)

    return []

# ======================
# DEBUG В TELEGRAM
# ======================

async def debug_api_raw():
    data = await fetch_hockey_today()

    text = "📦 RAW API ОТВЕТ (первые 10 матчей):\n\n"

    if not data:
        return "API вернул ПУСТОЙ список 😐"

    for g in data[:10]:

        text += (
            f"🏒 {g['league']['name']} | ID лиги: {g['league']['id']}\n"
            f"{g['teams']['home']['name']} vs {g['teams']['away']['name']}\n"
            f"Статус: {g['status']['short']} / {g['status']['long']}\n"
            f"Счёт: {g['scores']['home']}:{g['scores']['away']}\n"
            f"ID матча: {g['id']}\n"
            "----------------------\n"
        )

    return text

# ======================
# СБОР LIVE МАТЧЕЙ
# ======================

def is_live_status(status: str):
    return status in ["1P", "2P", "3P", "OT", "BT", "LIVE"]

async def get_live_matches():
    matches = []

    hockey = await fetch_hockey_today()

    for g in hockey:

        league_id = g["league"]["id"]

        if league_id not in user_data["selected_hockey"]:
            continue

        status = g["status"]["short"]

        if not is_live_status(status):
            continue

        matches.append({
            "id": f"hk_{g['id']}",
            "league": g["league"]["name"],
            "home": g["teams"]["home"]["name"],
            "away": g["teams"]["away"]["name"],
            "home_goals": g["scores"]["home"],
            "away_goals": g["scores"]["away"],
            "period": status,
            "sport": "hockey"
        })

    return matches


async def get_match_details(match_id, sport):

    matches = await get_live_matches()

    for m in matches:
        if m["id"] == match_id and m["sport"] == sport:
            return {
                "home": m["home"],
                "away": m["away"],
                "home_goals": m["home_goals"],
                "away_goals": m["away_goals"],
                "league": m["league"]
            }

    return None

# ======================
# TELEGRAM
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != YOUR_TELEGRAM_ID:
        return

    keyboard = [
        [InlineKeyboardButton("🔴 LIVE хоккей", callback_data="live")],
        [InlineKeyboardButton("📦 Показать RAW API", callback_data="debug")],
        [InlineKeyboardButton("⏹ Остановить", callback_data="stop")]
    ]

    await update.message.reply_text(
        "Бот готов.\nВыбран хоккей: NHL/KHL/VHL/MHL",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    matches = await get_live_matches()

    if not matches:
        await query.edit_message_text("Нет live матчей")
        return

    text = "LIVE:\n\n"
    keyboard = []

    i = 1
    for m in matches[:MATCHES_PER_PAGE]:

        score = f"{m['home_goals']}:{m['away_goals']}"

        text += f"{i}. {m['league']}\n{m['home']} {score} {m['away']}\n\n"

        keyboard.append([
            InlineKeyboardButton(
                f"Следить {i}",
                callback_data=f"monitor_{m['sport']}_{m['id']}"
            )
        ])

        i += 1

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def start_monitoring(update, context, sport, match_id):

    query = update.callback_query

    user_data["monitoring"] = {
        "match_id": match_id,
        "sport": sport,
        "last_score": {"home": 0, "away": 0}
    }

    context.application.job_queue.run_repeating(
        check_goals,
        interval=30,
        first=1,
        chat_id=query.message.chat_id,
        name=f"{sport}_{match_id}"
    )

    await query.edit_message_text("Отслеживание запущено")


async def stop_monitoring(update, context):

    query = update.callback_query

    user_data["monitoring"] = {
        "match_id": None,
        "sport": None,
        "last_score": {"home": 0, "away": 0}
    }

    await query.edit_message_text("Остановлено")


async def check_goals(context):

    mon = user_data["monitoring"]

    if not mon["match_id"]:
        return

    match = await get_match_details(mon["match_id"], mon["sport"])

    if not match:
        return

    new = {
        "home": match["home_goals"],
        "away": match["away_goals"]
    }

    if new != mon["last_score"]:

        msg = (
            f"ГОЛ!\n"
            f"{match['home']} {new['home']}:{new['away']} {match['away']}"
        )

        await context.bot.send_message(
            context.job.chat_id,
            msg
        )

        user_data["monitoring"]["last_score"] = new


async def button_handler(update, context):

    data = update.callback_query.data

    if data == "live":
        await show_live(update, context)

    elif data == "debug":
        query = update.callback_query
        await query.answer()

        text = await debug_api_raw()

        if len(text) > 3500:
            text = text[:3500] + "\n...обрезано..."

        await query.edit_message_text(text)

    elif data.startswith("monitor_"):
        p = data.split("_")
        await start_monitoring(update, context, p[1], p[2])

    elif data == "stop":
        await stop_monitoring(update, context)

# ======================
# ЗАПУСК
# ======================

def main():

    logging.basicConfig(level=logging.INFO)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":

    if not API_SPORTS_KEY:
        print("НЕТ API_SPORTS_KEY!")
        exit(1)

    main()
 

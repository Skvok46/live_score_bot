import aiohttp
import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ======================
# НАСТРОЙКИ
# ======================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")

# Лиги
# NHL → 57
# KHL → 35
# VHL → 36
# MHL → 37
# NMHL → 39

SELECTED_HOCKEY_LEAGUES = [57, 35, 36, 37, 39]

user_data = {
    "monitoring": {
        "match_id": None,
        "last_score": {"home": 0, "away": 0}
    }
}

MATCHES_PER_PAGE = 5


# ======================
# ВСПОМОГАТЕЛЬНОЕ
# ======================

def today():
    return datetime.now().strftime("%Y-%m-%d")


def is_live_status(status):
    return status in ["LIVE", "P1", "P2", "P3", "OT", "BT"]


# ======================
# API ЗАПРОС
# ======================

async def fetch_hockey_live():

    url = f"https://v1.hockey.api-sports.io/games?live=all"

    headers = {
        "x-apisports-key": API_SPORTS_KEY
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                return data.get("response", [])

    except Exception as e:
        logging.error("Hockey API error: %s", e)

    return []


# ======================
# СБОР LIVE МАТЧЕЙ
# ======================

async def get_live_matches():

    matches = []
    hockey = await fetch_hockey_live()

    for g in hockey:

        league_id = g["league"]["id"]

        if league_id not in SELECTED_HOCKEY_LEAGUES:
            continue

        status = g["status"]["short"]

        if not is_live_status(status):
            continue

        matches.append({
            "id": g["id"],
            "league": g["league"]["name"],
            "home": g["teams"]["home"]["name"],
            "away": g["teams"]["away"]["name"],
            "home_goals": g["scores"]["home"] or 0,
            "away_goals": g["scores"]["away"] or 0,
            "period": status
        })

    return matches


async def get_match_details(match_id):

    matches = await get_live_matches()

    for m in matches:
        if str(m["id"]) == str(match_id):
            return m

    return None


# ======================
# TELEGRAM
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != YOUR_TELEGRAM_ID:
        return

    keyboard = [
        [InlineKeyboardButton("🏒 LIVE", callback_data="live")],
        [InlineKeyboardButton("⏹ Остановить", callback_data="stop")]
    ]

    await update.message.reply_text(
        "Бот запущен.\nЛиги: NHL / KHL / VHL / MHL / NMHL",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    matches = await get_live_matches()

    if not matches:
        await query.edit_message_text("❌ Сейчас нет LIVE матчей")
        return

    text = "🏒 LIVE:\n\n"
    keyboard = []

    for i, m in enumerate(matches[:MATCHES_PER_PAGE], start=1):

        score = f"{m['home_goals']}:{m['away_goals']}"

        text += (
            f"{i}. {m['league']}\n"
            f"{m['home']} {score} {m['away']}\n"
            f"Период: {m['period']}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"Следить {i}",
                callback_data=f"monitor_{m['id']}"
            )
        ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def start_monitoring(update, context, match_id):

    query = update.callback_query

    user_data["monitoring"] = {
        "match_id": match_id,
        "last_score": {"home": 0, "away": 0}
    }

    context.application.job_queue.run_repeating(
        check_goals,
        interval=30,
        first=1,
        chat_id=query.message.chat_id,
        name=f"monitor_{match_id}"
    )

    await query.edit_message_text("✅ Отслеживание запущено")


async def stop_monitoring(update, context):

    query = update.callback_query

    user_data["monitoring"] = {
        "match_id": None,
        "last_score": {"home": 0, "away": 0}
    }

    await query.edit_message_text("⏹ Остановлено")


async def check_goals(context):

    mon = user_data["monitoring"]

    if not mon["match_id"]:
        return

    match = await get_match_details(mon["match_id"])

    if not match:
        return

    new_score = {
        "home": match["home_goals"],
        "away": match["away_goals"]
    }

    if new_score != mon["last_score"]:

        msg = (
            f"🚨 ГОЛ!\n"
            f"{match['home']} {new_score['home']}:{new_score['away']} {match['away']}"
        )

        await context.bot.send_message(
            context.job.chat_id,
            msg
        )

        user_data["monitoring"]["last_score"] = new_score


async def button_handler(update, context):

    data = update.callback_query.data

    if data == "live":
        await show_live(update, context)

    elif data.startswith("monitor_"):
        match_id = data.split("_")[1]
        await start_monitoring(update, context, match_id)

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

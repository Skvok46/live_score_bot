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
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))

# 🧠 Данные пользователя
user_data = {
    "selected_football": [78],  # Бундеслига
    "selected_hockey": [105, 106, 107],  # КХЛ, ВХЛ, МХЛ
    "monitoring": {
        "match_id": None,
        "sport": None,
        "last_score": {"home": 0, "away": 0}
    },
    "check_interval": 30
}

ALL_FOOTBALL_LEAGUES = [{"id": 78, "name": "Бундеслига (Германия)"}]
ALL_HOCKEY_LEAGUES = [
    {"id": 105, "name": "КХЛ (Россия)"},
    {"id": 106, "name": "ВХЛ (Россия)"},
    {"id": 107, "name": "МХЛ (Россия)"},
]

MATCHES_PER_PAGE = 5

# ======================
# 🌐 ИСТОЧНИКИ ДАННЫХ
# ======================

async def fetch_bundesliga_live():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.openligadb.de/api/getmatchdata/bl1",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logging.error("Ошибка OpenLigaDB: %s", e)

    return []


async def fetch_khl_live():
    try:
        today = time.strftime("%Y-%m-%d")
        url = "https://api.khl.ru/v1/schedule/seasons/2025/games?date=%s&status=2" % today

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()

    except Exception as e:
        logging.error("Ошибка KHL API: %s", e)

    return {"games": []}

# ======================
# 📅 ПОЛУЧЕНИЕ МАТЧЕЙ
# ======================

async def get_live_matches():
    matches = []

    # Бундеслига
    if 78 in user_data["selected_football"]:
        data = await fetch_bundesliga_live()

        for match in data:
            if not match.get("MatchIsFinished", True) and match.get("MatchResults"):
                home = match["Team1"]["TeamName"]
                away = match["Team2"]["TeamName"]
                res = match["MatchResults"][0]

                matches.append({
                    "id": "bl_%s" % match['MatchID'],
                    "league": "Бундеслига",
                    "home": home,
                    "away": away,
                    "home_goals": res.get("PointsTeam1", 0),
                    "away_goals": res.get("PointsTeam2", 0),
                    "elapsed": match.get("TimeElapsed", "?"),
                    "sport": "football"
                })

    # КХЛ / ВХЛ / МХЛ
    if any(lid in [105, 106, 107] for lid in user_data["selected_hockey"]):
        data = await fetch_khl_live()

        for game in data.get("games", []):
            matches.append({
                "id": "khl_%s" % game['id'],
                "league": game.get("stage", "Хоккей"),
                "home": game["homeTeam"]["name"],
                "away": game["awayTeam"]["name"],
                "home_goals": game.get("homeScore", 0),
                "away_goals": game.get("awayScore", 0),
                "period": game.get("period", "?"),
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
                "status": "LIVE",
                "league": m["league"]
            }

    return None

# ======================
# 🤖 TELEGRAM
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
        [InlineKeyboardButton("⏹️ Остановить отслеживание", callback_data='stop')],
    ]

    await update.message.reply_text(
        "Бот live-уведомлений запущен.\nИнтервал проверки: 30 сек",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    matches = await get_live_matches()

    if not matches:
        await query.edit_message_text("Нет активных матчей.")
        return

    text = "🔴 Сейчас идут матчи:\n\n"
    keyboard = []

    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        score = "%s:%s" % (m['home_goals'], m['away_goals'])
        time_info = m.get('elapsed', m.get('period', '?'))

        text += "%s. %s • %s'\n%s %s %s\n\n" % (
            i, m['league'], time_info,
            m['home'], score, m['away']
        )

        keyboard.append([
            InlineKeyboardButton(
                "🎯 Отслеживать матч %s" % i,
                callback_data="monitor_%s_%s" % (m['sport'], m['id'])
            )
        ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def check_goals(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    monitoring = user_data["monitoring"]

    match_id = monitoring["match_id"]
    sport = monitoring["sport"]

    if not match_id:
        return

    match = await get_match_details(match_id, sport)

    if not match:
        return

    new_score = {
        "home": match["home_goals"],
        "away": match["away_goals"]
    }

    if new_score != monitoring["last_score"]:
        msg = "🚨 ГОЛ!\n%s %s–%s %s" % (
            match["home"],
            match["home_goals"],
            match["away_goals"],
            match["away"]
        )

        await context.bot.send_message(chat_id, msg)

        user_data["monitoring"]["last_score"] = new_score


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == 'live':
        await show_live(update, context)

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
    print("🚀 Бот запускается...")
    main()
    

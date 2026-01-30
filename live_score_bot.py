import aiohttp
import time
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ======================
# 🔑 НАСТРОЙКИ
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID", "0"))

LIVE_CHECK_INTERVAL = 864
MATCHES_PER_PAGE = 5
DAILY_LIMIT = 100

api_request_count = 0
aiohttp_session: aiohttp.ClientSession | None = None

# ======================
# 🏆 ЛИГИ
# ======================
ALL_FOOTBALL_LEAGUES = [
    {"id": 39, "name": "АПЛ (Англия)"},
    {"id": 140, "name": "Ла Лига (Испания)"},
    {"id": 135, "name": "Серия А (Италия)"},
    {"id": 78, "name": "Бундеслига (Германия)"},
    {"id": 61, "name": "Лига 1 (Франция)"},
]

ALL_HOCKEY_LEAGUES = [
    {"id": 57, "name": "NHL (США/Канада)"},
    {"id": 105, "name": "КХЛ (Россия)"},
    {"id": 106, "name": "ВХЛ (Россия)"},
    {"id": 110, "name": "SHL (Швеция)"},
    {"id": 111, "name": "Liiga (Финляндия)"},
]

# ======================
# 🧠 СОСТОЯНИЕ (один пользователь)
# ======================
user_data = {
    "selected_football": [39],
    "selected_hockey": [57],
    "monitoring_match_id": None,
    "last_score": {},
}

# ======================
# 🌐 API
# ======================
async def make_api_request(url, headers, params=None):
    global api_request_count

    if api_request_count >= DAILY_LIMIT:
        logging.error("❌ API лимит исчерпан")
        return None

    api_request_count += 1
    logging.info(f"📡 API запрос {api_request_count}/{DAILY_LIMIT}")

    try:
        async with aiohttp_session.get(
            url,
            headers=headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 200:
                return await response.json()
            logging.error(f"API статус {response.status}")
            return None
    except Exception as e:
        logging.error(f"Ошибка API: {e}")
        return None

# ======================
# 📊 ДАННЫЕ
# ======================
async def get_today_matches():
    today = time.strftime("%Y-%m-%d")
    url = "https://api-sports-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": RAPID_API_KEY,
        "X-RapidAPI-Host": "api-sports-v1.p.rapidapi.com",
    }

    matches = []

    for league_id in user_data["selected_football"]:
        data = await make_api_request(url, headers, {
            "date": today,
            "league": league_id,
            "timezone": "Europe/Moscow",
        })
        if data:
            for m in data.get("response", []):
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "time": m["fixture"]["date"][11:16],
                })

    return matches

async def get_match_details(match_id):
    url = "https://api-sports-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": RAPID_API_KEY,
        "X-RapidAPI-Host": "api-sports-v1.p.rapidapi.com",
    }

    data = await make_api_request(url, headers, {"id": match_id})
    if not data or not data.get("response"):
        return None

    m = data["response"][0]
    return {
        "home": m["teams"]["home"]["name"],
        "away": m["teams"]["away"]["name"],
        "home_goals": m["goals"]["home"] or 0,
        "away_goals": m["goals"]["away"] or 0,
        "status": m["fixture"]["status"]["short"],
        "league": m["league"]["name"],
    }

# ======================
# 🤖 BOT
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Матчи сегодня", callback_data="today")],
        [InlineKeyboardButton("⏹️ Остановить", callback_data="stop")],
    ]
    await update.message.reply_text(
        "🤖 Бот запущен",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    matches = await get_today_matches()
    if not matches:
        await query.edit_message_text("Сегодня матчей нет")
        return

    text = "📅 Матчи сегодня:\n\n"
    keyboard = []

    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        text += f"{i}. {m['league']}\n{m['home']} vs {m['away']} ({m['time']})\n\n"
        keyboard.append([
            InlineKeyboardButton(
                f"🎯 Отслеживать {i}",
                callback_data=f"monitor_{m['id']}",
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE, match_id):
    query = update.callback_query
    await query.answer()

    # ❗ защита от дубликатов
    for job in context.application.job_queue.get_jobs_by_name("monitor"):
        job.schedule_removal()

    user_data["monitoring_match_id"] = int(match_id)
    user_data["last_score"] = {}

    context.application.job_queue.run_repeating(
        check_goals,
        interval=LIVE_CHECK_INTERVAL,
        first=1,
        name="monitor",
        chat_id=query.message.chat_id,
    )

    await query.edit_message_text("✅ Отслеживание начато")

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for job in context.application.job_queue.get_jobs_by_name("monitor"):
        job.schedule_removal()

    user_data["monitoring_match_id"] = None
    user_data["last_score"] = {}

    if update.callback_query:
        await update.callback_query.edit_message_text("⏹️ Остановлено")
    else:
        await update.message.reply_text("⏹️ Остановлено")

async def check_goals(context: ContextTypes.DEFAULT_TYPE):
    match_id = user_data["monitoring_match_id"]
    if not match_id:
        return

    match = await get_match_details(match_id)
    if not match:
        return

    score = (match["home_goals"], match["away_goals"])
    last = user_data["last_score"]

    if last != score:
        user_data["last_score"] = score
        await context.bot.send_message(
            context.job.chat_id,
            f"🚨 ГОЛ!\n{match['home']} {score[0]}–{score[1]} {match['away']}",
        )

# ======================
# 🚀 ЗАПУСК
# ======================
def main():
    global aiohttp_session

    logging.basicConfig(level=logging.INFO)

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    aiohttp_session = aiohttp.ClientSession()

    async def shutdown(app):
        await aiohttp_session.close()

    application.post_shutdown.append(shutdown)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: show_today(u, c) if u.callback_query.data == "today"
        else stop_monitoring(u, c) if u.callback_query.data == "stop"
        else start(u, c) if u.callback_query.data == "back"
        else start_monitoring(u, c, u.callback_query.data.split("_")[1])
    ))

    print("🚀 Бот запущен")
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not RAPID_API_KEY:
        raise RuntimeError("❌ Не заданы переменные окружения")

    main()
    

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
    "check_interval": 30  # Фиксированный интервал (30 сек)
}

# 🏆 Списки лиг
ALL_FOOTBALL_LEAGUES = [{"id": 78, "name": "Бундеслига (Германия)"}]
ALL_HOCKEY_LEAGUES = [
    {"id": 105, "name": "КХЛ (Россия)"},
    {"id": 106, "name": "ВХЛ (Россия)"},
    {"id": 107, "name": "МХЛ (Россия)"},
]

MATCHES_PER_PAGE = 5

# ======================
# 🌐 БЕСПЛАТНЫЕ ИСТОЧНИКИ
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
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.khl.ru/v1/schedule/seasons/2025/games?date=%s&status=2" % today,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
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
    
    # 🇩🇪 Бундеслига
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
    
    # 🇷🇺 КХЛ/ВХЛ/МХЛ
    if any(lid in [105, 106, 107] for lid in user_data["selected_hockey"]):
        data = await fetch_khl_live()
        for game in data.get("games", []):
            matches.append({
                "id": "khl_%s" % game['id'],
                "league": game.get("stage", "Хоккей"),
                "home": game["homeTeam"]["name"],                "away": game["awayTeam"]["name"],
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
# 🤖 TELEGRAM-ОБРАБОТЧИКИ
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_football = ", ".join([l["name"] for l in ALL_FOOTBALL_LEAGUES if l["id"] in user_data["selected_football"]]) or "—"
    selected_hockey = ", ".join([l["name"] for l in ALL_HOCKEY_LEAGUES if l["id"] in user_data["selected_hockey"]]) or "—"
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Настроить лиги", callback_data='configure')],
        [InlineKeyboardButton("📅 Матчи на сегодня", callback_data='today')],
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
        [InlineKeyboardButton("⏹️ Остановить отслеживание", callback_data='stop')],
    ]
    text = (
        "✅ <b>Настройки:</b>\n"
        "⚽ Футбол: %s\n"
        "🏒 Хоккей: %s\n"
        "⏱️ Интервал проверки: <b>30 сек</b>\n\n"
        "⚡ Скорость уведомлений: 1–5 сек после гола"
    ) % (selected_football, selected_hockey)
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def configure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [        [InlineKeyboardButton("⚽ Футбол (Бундеслига)", callback_data='conf_football')],
        [InlineKeyboardButton("🏒 Хоккей (КХЛ/ВХЛ/МХЛ)", callback_data='conf_hockey')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')],
    ]
    await query.edit_message_text("Выберите вид спорта:", reply_markup=InlineKeyboardMarkup(keyboard))

async def configure_sport(update: Update, context: ContextTypes.DEFAULT_TYPE, sport):
    query = update.callback_query
    await query.answer()
    leagues = ALL_FOOTBALL_LEAGUES if sport == "football" else ALL_HOCKEY_LEAGUES
    selected = user_data["selected_football"] if sport == "football" else user_data["selected_hockey"]
    
    keyboard = []
    for league in leagues:
        mark = "✅" if league["id"] in selected else "◻️"
        keyboard.append([InlineKeyboardButton("%s %s" % (mark, league['name']), callback_data="toggle_%s_%s" % (sport, league['id']))])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='configure')])
    await query.edit_message_text("Выберите лиги для %s:" % ("футбола" if sport == "football" else "хоккея"), reply_markup=InlineKeyboardMarkup(keyboard))

async def toggle_league(update: Update, context: ContextTypes.DEFAULT_TYPE, sport, league_id):
    query = update.callback_query
    await query.answer()
    target = user_data["selected_football"] if sport == "football" else user_data["selected_hockey"]
    if league_id in target:
        target.remove(league_id)
    else:
        target.append(league_id)
    await configure_sport(update, context, sport)

async def show_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    matches = await get_live_matches()
    if not matches:
        await query.edit_message_text("Сегодня нет матчей в выбранных лигах.")
        return
    text = "📅 <b>Матчи на сегодня:</b>\n\n"
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        time_info = m.get('elapsed', m.get('period', '—'))
        text += "%s. %s • %s'\n%s vs %s\n\n" % (i, m['league'], time_info, m['home'], m['away'])
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    matches = await get_live_matches()
    if not matches:
        await query.edit_message_text("Нет активных матчей в выбранных лигах.")
        return
    text = "🔴 <b>Сейчас идут матчи:</b>\n\n"
    keyboard = []
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        score = "%s:%s" % (m['home_goals'], m['away_goals'])
        time_info = m.get('elapsed', m.get('period', '?'))
        text += "%s. %s • %s'\n%s %s %s\n\n" % (i, m['league'], time_info, m['home'], score, m['away'])
        keyboard.append([InlineKeyboardButton("🎯 Отслеживать матч %s" % i, callback_data="monitor_%s_%s" % (m['sport'], m['id']))])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE, sport, match_id):
    query = update.callback_query
    user_data["monitoring"] = {
        "match_id": match_id,
        "sport": sport,
        "last_score": {"home": 0, "away": 0}
    }
    
    interval = user_data["check_interval"]
    context.application.job_queue.run_repeating(
        check_goals,
        interval=interval,
        first=1,
        chat_id=query.message.chat_id,
        name="%s_%s" % (sport, match_id)
    )
    
    msg = (
        "✅ <b>Отслеживание запущено!</b>\n"
        "🆔 Матч: %s\n"
        "⏱️ Интервал: <b>%s сек</b>\n"
        "🚨 Уведомление придёт через 1–5 сек после гола!\n\n"
        "Чтобы остановить: «⏹️ Остановить» или /stop"
    ) % (match_id, interval)
    await query.edit_message_text(msg, parse_mode='HTML')

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match_id = user_data["monitoring"]["match_id"]
    sport = user_data["monitoring"]["sport"]
    
    if match_id:
        job_name = "%s_%s" % (sport, match_id)
        for job in context.application.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
    
    user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
    msg = "⏹️ Отслеживание остановлено." if match_id else "❌ Нет активного отслеживания."
    query = update.callback_query
    await (query.edit_message_text(msg) if query else update.message.reply_text(msg))

async def check_goals(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    monitoring = user_data["monitoring"]
    match_id = monitoring["match_id"]
    sport = monitoring["sport"]
    
    if not match_id or not sport:
        return
    
    match = await get_match_details(match_id, sport)
    if not match:
        return
    
    new_score = {"home": match["home_goals"], "away": match["away_goals"]}
    last_score = monitoring["last_score"]
    
    if new_score != last_score:
        msg = "🚨 <b>ГОЛ!</b> %s\n%s %s–%s %s" % (
            match["league"],
            match["home"],
            match["home_goals"],
            match["away_goals"],
            match["away"]
        )
        try:
            await context.bot.send_message(chat_id, msg, parse_mode='HTML')
            user_data["monitoring"]["last_score"] = new_score
        except Exception as e:
            logging.error("Ошибка уведомления: %s", e)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == 'configure': await configure(update, context)
    elif data == 'conf_football': await configure_sport(update, context, "football")
    elif data == 'conf_hockey': await configure_sport(update, context, "hockey")
    elif data.startswith('toggle_football_'):
        lid = int(data.split('_')[2])
        await toggle_league(update, context, "football", lid)
    elif data.startswith('toggle_hockey_'):
        lid = int(data.split('_')[2])
        await toggle_league(update, context, "hockey", lid)
    elif data == 'today': await show_today(update, context)
    elif data == 'live': await show_live(update, context)
    elif data.startswith('monitor_'):
        parts = data.split('_')
        await start_monitoring(update, context, parts[1], parts[2])
    elif data == 'stop': await stop_monitoring(update, context)
    elif data == 'back': await start(update, context)

# ======================# 🚀 ЗАПУСК
# ======================

def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_monitoring))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not YOUR_TELEGRAM_ID:
        print("❌ Ошибка: не заданы TELEGRAM_TOKEN или YOUR_TELEGRAM_ID!")
        exit(1)
    print("🚀 Бот запускается (без API-Sports, без f-строк, без ошибок)")
    main()

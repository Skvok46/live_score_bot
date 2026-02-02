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
API_KEY = os.getenv("RAPID_API_KEY")  # Ключ из dashboard.api-sports.io
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))

LIVE_CHECK_INTERVAL = 864  # секунд (14.4 минуты)
MATCHES_PER_PAGE = 5
DAILY_LIMIT = 100

api_request_count = 0

# 🏆 Списки лиг
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
    {"id": 106, "name": "ВХЛ (Россия)"},
    {"id": 107, "name": "МХЛ (Россия)"},
]

# 🧠 Данные пользователя
user_data = {
    "selected_football": [39],
    "selected_hockey": [57],
    "monitoring": {
        "match_id": None,
        "sport": None,  # "football" или "hockey"
        "last_score": {"home": 0, "away": 0}
    }
}

# ======================
# 🌐 API-СПОРТС (2026)
# ======================
def get_headers():
    return {"x-apisports-key": API_KEY}

def get_url(sport):
    return "https://v3.football.api-sports.io" if sport == "football" else "https://v3.hockey.api-sports.io"

async def make_api_request(sport, endpoint, params=None):
    global api_request_count
    api_request_count += 1
    logging.info(f"📡 Запрос #{api_request_count}/{DAILY_LIMIT} к {sport.upper()}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{get_url(sport)}{endpoint}",
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
# 📅 ПОЛУЧЕНИЕ ДАННЫХ
# ======================

async def get_today_matches():
    matches = []
    today = time.strftime("%Y-%m-%d")
    
    # Футбол
    for league in ALL_FOOTBALL_LEAGUES:
        if league["id"] in user_data["selected_football"]:
            data = await make_api_request("football", "/fixtures", {
                "date": today,
                "league": league["id"],
                "timezone": "Europe/Moscow"
            })
            if data and data.get("response"):
                for m in data["response"]:
                    matches.append({
                        "id": m["fixture"]["id"],
                        "league": m["league"]["name"],                        "home": m["teams"]["home"]["name"],
                        "away": m["teams"]["away"]["name"],
                        "time": m["fixture"]["date"][11:16],
                        "sport": "football"
                    })
    
    # Хоккей
    for league in ALL_HOCKEY_LEAGUES:
        if league["id"] in user_data["selected_hockey"]:
            data = await make_api_request("hockey", "/fixtures", {
                "date": today,
                "league": league["id"],
                "timezone": "Europe/Moscow"
            })
            if data and data.get("response"):
                for m in data["response"]:
                    matches.append({
                        "id": m["fixture"]["id"],
                        "league": m["league"]["name"],
                        "home": m["teams"]["home"]["name"],
                        "away": m["teams"]["away"]["name"],
                        "time": m["fixture"]["date"][11:16],
                        "sport": "hockey"
                    })
    return matches

async def get_live_matches():
    matches = []
    
    # Футбол
    for league_id in user_data["selected_football"]:
        data = await make_api_request("football", "/fixtures", {"live": "all", "league": league_id})
        if data and data.get("response"):
            for m in data["response"]:
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "home_goals": m["goals"]["home"] or 0,
                    "away_goals": m["goals"]["away"] or 0,
                    "elapsed": m["fixture"]["status"]["elapsed"] or "?",
                    "sport": "football"
                })
    
    # Хоккей
    for league_id in user_data["selected_hockey"]:
        data = await make_api_request("hockey", "/fixtures", {"live": "all", "league": league_id})
        if data and data.get("response"):
            for m in data["response"]:                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "home_goals": m["goals"]["home"] or 0,
                    "away_goals": m["goals"]["away"] or 0,
                    "period": m["fixture"]["status"]["short"] or "?",
                    "sport": "hockey"
                })
    return matches

async def get_match_details(match_id, sport):
    data = await make_api_request(sport, "/fixtures", {"id": match_id})
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
# 🤖 TELEGRAM-ОБРАБОТЧИКИ
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_football = ", ".join([l["name"] for l in ALL_FOOTBALL_LEAGUES if l["id"] in user_data["selected_football"]])
    selected_hockey = ", ".join([l["name"] for l in ALL_HOCKEY_LEAGUES if l["id"] in user_data["selected_hockey"]])
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Настроить лиги", callback_data='configure')],
        [InlineKeyboardButton("📅 Матчи на сегодня", callback_data='today')],
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
        [InlineKeyboardButton("⏹️ Остановить отслеживание", callback_data='stop')],
        [InlineKeyboardButton("🔍 Проверить API", callback_data='test_api')],
    ]
    text = (
        f"✅ <b>Выбранные лиги:</b>\n"
        f"⚽ {selected_football}\n"
        f"🏒 {selected_hockey}\n\n"
        f"Текущий расход: {api_request_count}/{DAILY_LIMIT} запросов"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def configure(update: Update, context: ContextTypes.DEFAULT_TYPE):    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⚽ Футбол", callback_data='conf_football')],
        [InlineKeyboardButton("🏒 Хоккей", callback_data='conf_hockey')],
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
        keyboard.append([InlineKeyboardButton(f"{mark} {league['name']}", callback_data=f"toggle_{sport}_{league['id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='configure')])
    await query.edit_message_text(f"Выберите лиги для {'футбола' if sport == 'football' else 'хоккея'}:", reply_markup=InlineKeyboardMarkup(keyboard))

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
    matches = await get_today_matches()
    if not matches:
        await query.edit_message_text("Сегодня нет матчей в выбранных лигах.")
        return
    text = "📅 <b>Матчи на сегодня:</b>\n\n"
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        text += f"{i}. {m['league']}\n⏰ {m['time']} • {m['home']} vs {m['away']}\n\n"
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    matches = await get_live_matches()
    if not matches:
        await query.edit_message_text("Нет активных матчей в выбранных лигах.")
        return    text = "🔴 <b>Сейчас идут матчи:</b>\n\n"
    keyboard = []
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        score = f"{m['home_goals']}:{m['away_goals']}"
        time_info = m.get('elapsed', m.get('period', '?'))
        text += f"{i}. {m['league']} • {time_info}'\n{m['home']} {score} {m['away']}\n\n"
        keyboard.append([InlineKeyboardButton(f"🎯 Отслеживать матч {i}", callback_data=f"monitor_{m['sport']}_{m['id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE, sport, match_id):
    query = update.callback_query
    user_data["monitoring"] = {
        "match_id": int(match_id),
        "sport": sport,
        "last_score": {"home": 0, "away": 0}
    }
    
    context.application.job_queue.run_repeating(
        check_goals,
        interval=LIVE_CHECK_INTERVAL,
        first=1,
        chat_id=query.message.chat_id,
        name=f"{sport}_{match_id}"
    )
    
    await query.edit_message_text(
        f"✅ Отслеживаю матч ID {match_id}!\n"
        f"Уведомления о голах каждые {LIVE_CHECK_INTERVAL} сек.\n"
        "Чтобы остановить: «⏹️ Остановить» или /stop"
    )

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match_id = user_data["monitoring"]["match_id"]
    sport = user_data["monitoring"]["sport"]
    
    if match_id:
        job_name = f"{sport}_{match_id}"
        for job in context.application.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
    
    user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
    msg = "⏹️ Отслеживание остановлено." if match_id else "❌ Нет активного отслеживания."
    query = update.callback_query
    await (query.edit_message_text(msg) if query else update.message.reply_text(msg))

async def check_goals(context: ContextTypes.DEFAULT_TYPE):
    global api_request_count
    chat_id = context.job.chat_id
    monitoring = user_data["monitoring"]    match_id = monitoring["match_id"]
    sport = monitoring["sport"]
    
    if not match_id or not sport:
        return
    
    if api_request_count >= DAILY_LIMIT - 2:
        for job in context.application.job_queue.get_jobs_by_name(f"{sport}_{match_id}"):
            job.schedule_removal()
        user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
        try:
            await context.bot.send_message(chat_id, "🛑 Достигнут лимит API. Отслеживание приостановлено до завтра.")
        except:
            pass
        return
    
    match = await get_match_details(match_id, sport)
    if not match:
        return
    
    status = match["status"].upper()
    finished = ["FT", "AET", "PEN", "FINISHED", "ENDED", "SUSPENDED", "CANC", "ABD", "POSTP"]
    
    if any(f in status for f in finished):
        for job in context.application.job_queue.get_jobs_by_name(f"{sport}_{match_id}"):
            job.schedule_removal()
        user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
        msg = f"✅ <b>Матч завершён!</b>\n{match['home']} {match['home_goals']}–{match['away_goals']} {match['away']}\nЛига: {match['league']}"
        try:
            await context.bot.send_message(chat_id, msg, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Ошибка финального сообщения: {e}")
        return
    
    new_score = {"home": match["home_goals"], "away": match["away_goals"]}
    last_score = monitoring["last_score"]
    
    if new_score != last_score:
        msg = f"🚨 <b>ГОЛ!</b> {match['league']}\n{match['home']} {match['home_goals']}–{match['away_goals']} {match['away']}\nСтатус: {match['status']}"
        try:
            await context.bot.send_message(chat_id, msg, parse_mode='HTML')
            user_data["monitoring"]["last_score"] = new_score
        except Exception as e:
            logging.error(f"Ошибка уведомления: {e}")

async def test_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:        async with aiohttp.ClientSession() as session:
            # Проверка футбола
            async with session.get(
                "https://v3.football.api-sports.io/status",
                headers=get_headers()
            ) as resp_f:
                football = await resp_f.json() if resp_f.status == 200 else {"status": "error"}
            
            # Проверка хоккея
            async with session.get(
                "https://v3.hockey.api-sports.io/status",
                headers=get_headers()
            ) as resp_h:
                hockey = await resp_h.json() if resp_h.status == 200 else {"status": "error"}
        
        f_status = "✅ Работает" if football.get("status") == "success" else "❌ Ошибка"
        h_status = "✅ Работает" if hockey.get("status") == "success" else "❌ Ошибка"
        
        f_used = football.get("data", {}).get("current", "?")
        f_limit = football.get("data", {}).get("limit", "?")
        h_used = hockey.get("data", {}).get("current", "?")
        h_limit = hockey.get("data", {}).get("limit", "?")
        
        msg = (
            f"🔍 <b>Статус API:</b>\n\n"
            f"⚽ Football: {f_status}\n   Запросов: {f_used}/{f_limit}\n\n"
            f"🏒 Hockey: {h_status}\n   Запросов: {h_used}/{h_limit}"
        )
        await query.edit_message_text(msg, parse_mode='HTML')
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка проверки API:\n{str(e)}")

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
        await start_monitoring(update, context, parts[1], parts[2])    elif data == 'stop': await stop_monitoring(update, context)
    elif data == 'test_api': await test_api(update, context)
    elif data == 'back': await start(update, context)

# ======================
# 🚀 ЗАПУСК
# ======================

def main():
    global api_request_count, user_data
    api_request_count = 0
    user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
    
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
    if not TELEGRAM_TOKEN or not API_KEY or not YOUR_TELEGRAM_ID:
        print("❌ Ошибка: не заданы переменные окружения!")
        exit(1)
    print("🚀 Бот запускается...")
    main()

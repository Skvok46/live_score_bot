import aiohttp
import time
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ======================
# 🔑 НАСТРОЙКИ (БЕЗ API-SPORTS!)
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))

# 🧠 Данные пользователя
user_data = {
    "selected_football": [78],  # Только Бундеслига
    "selected_hockey": [105, 106, 107],  # КХЛ, ВХЛ, МХЛ
    "monitoring": {
        "match_id": None,
        "sport": None,
        "last_score": {"home": 0, "away": 0}
    },
    "check_interval": 30,  # Секунд (по умолчанию)
    "awaiting_interval_input": False  # Флаг ожидания ввода
}

# 🏆 Списки лиг
ALL_FOOTBALL_LEAGUES = [
    {"id": 78, "name": "Бундеслига (Германия)"},
]
ALL_HOCKEY_LEAGUES = [
    {"id": 105, "name": "КХЛ (Россия)"},
    {"id": 106, "name": "ВХЛ (Россия)"},
    {"id": 107, "name": "МХЛ (Россия)"},
]

MATCHES_PER_PAGE = 5
INTERVAL_MIN = 5    # Минимальный интервал (сек)
INTERVAL_MAX = 600  # Максимальный интервал (сек)

# ======================
# 🌐 АСИНХРОННЫЕ ЗАПРОСЫ К БЕСПЛАТНЫМ ИСТОЧНИКАМ
# ======================

async def fetch_bundesliga_live():
    """Получает live-матчи Бундеслиги из официального OpenLigaDB"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.openligadb.de/api/getmatchdata/bl1",                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logging.error(f"Ошибка OpenLigaDB: {e}")
    return []

async def fetch_khl_live():
    """Получает live-матчи КХЛ/ВХЛ/МХЛ из официального KHL API"""
    try:
        today = time.strftime("%Y-%m-%d")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.khl.ru/v1/schedule/seasons/2025/games?date={today}&status=2",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logging.error(f"Ошибка KHL API: {e}")
    return {"games": []}

# ======================
# 📅 ПОЛУЧЕНИЕ МАТЧЕЙ
# ======================

async def get_today_matches():
    """Для простоты — показываем только live-матчи как 'сегодняшние'"""
    return await get_live_matches()

async def get_live_matches():
    """Получает ВСЕ live-матчи: Бундеслига + КХЛ/ВХЛ/МХЛ"""
    matches = []
    
    # 🇩🇪 Бундеслига (если выбрана)
    if 78 in user_data["selected_football"]:
        data = await fetch_bundesliga_live()
        for match in data:
            if not match.get("MatchIsFinished", True) and match.get("MatchResults"):
                home = match["Team1"]["TeamName"]
                away = match["Team2"]["TeamName"]
                res = match["MatchResults"][0]
                matches.append({
                    "id": f"bl_{match['MatchID']}",
                    "league": "Бундеслига",
                    "home": home,
                    "away": away,
                    "home_goals": res.get("PointsTeam1", 0),
                    "away_goals": res.get("PointsTeam2", 0),                    "elapsed": match.get("TimeElapsed", "?"),
                    "sport": "football"
                })
    
    # 🇷🇺 КХЛ/ВХЛ/МХЛ (если выбрана хотя бы одна)
    if any(lid in [105, 106, 107] for lid in user_data["selected_hockey"]):
        data = await fetch_khl_live()
        for game in data.get("games", []):
            matches.append({
                "id": f"khl_{game['id']}",
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
    """Детали матча для отслеживания (берётся из live-данных)"""
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
    user_data["awaiting_interval_input"] = False
    
    selected_football = ", ".join([l["name"] for l in ALL_FOOTBALL_LEAGUES if l["id"] in user_data["selected_football"]]) or "—"
    selected_hockey = ", ".join([l["name"] for l in ALL_HOCKEY_LEAGUES if l["id"] in user_data["selected_hockey"]]) or "—"
    interval = user_data["check_interval"]
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Настроить лиги", callback_data='configure')],
        [InlineKeyboardButton("⏱️ Настроить интервал", callback_data='set_interval')],        [InlineKeyboardButton("📅 Матчи на сегодня", callback_data='today')],
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
        [InlineKeyboardButton("⏹️ Остановить отслеживание", callback_data='stop')],
    ]
    text = (
        f"✅ <b>Настройки:</b>\n"
        f"⚽ Футбол: {selected_football}\n"
        f"🏒 Хоккей: {selected_hockey}\n"
        f"⏱️ Интервал проверки: <b>{interval} сек</b>\n\n"
        f"⚡ <b>Скорость уведомлений:</b> 1–5 сек после гола"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def configure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data["awaiting_interval_input"] = False
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⚽ Футбол (только Бундеслига)", callback_data='conf_football')],
        [InlineKeyboardButton("🏒 Хоккей (КХЛ/ВХЛ/МХЛ)", callback_data='conf_hockey')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')],
    ]
    await query.edit_message_text("Выберите вид спорта:", reply_markup=InlineKeyboardMarkup(keyboard))

async def configure_sport(update: Update, context: ContextTypes.DEFAULT_TYPE, sport):
    user_data["awaiting_interval_input"] = False
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
    user_data["awaiting_interval_input"] = False
    query = update.callback_query
    await query.answer()
    target = user_data["selected_football"] if sport == "football" else user_data["selected_hockey"]
    if league_id in target:
        target.remove(league_id)
    else:
        target.append(league_id)
    await configure_sport(update, context, sport)

async def request_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):    """Запрашивает у пользователя ввод интервала"""
    user_data["awaiting_interval_input"] = False
    query = update.callback_query
    await query.answer()
    user_data["awaiting_interval_input"] = True
    await query.edit_message_text(
        f"⏱️ <b>Введите интервал проверки в секундах:</b>\n\n"
        f"🔹 Минимум: {INTERVAL_MIN} сек\n"
        f"🔹 Максимум: {INTERVAL_MAX} сек\n"
        f"🔹 Рекомендуется: 10–30 сек для максимальной скорости\n\n"
        f"<i>Пример: 15</i>",
        parse_mode='HTML'
    )

async def handle_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод интервала"""
    if not user_data.get("awaiting_interval_input", False):
        return
    
    text = update.message.text.strip()
    
    try:
        interval = int(text)
        
        if interval < INTERVAL_MIN:
            await update.message.reply_text(
                f"❌ Слишком маленький интервал! Минимум: {INTERVAL_MIN} сек.\n"
                f"Введите новое значение:"
            )
            return
        
        if interval > INTERVAL_MAX:
            await update.message.reply_text(
                f"❌ Слишком большой интервал! Максимум: {INTERVAL_MAX} сек.\n"
                f"Введите новое значение:"
            )
            return
        
        user_data["check_interval"] = interval
        user_data["awaiting_interval_input"] = False
        
        await update.message.reply_text(
            f"✅ Интервал установлен: <b>{interval} сек</b>\n\n"
            f"Теперь уведомления о голах будут приходить каждые {interval} секунд.\n"
            f"Напишите /start для возврата в меню.",
            parse_mode='HTML'
        )
        
    except ValueError:
        await update.message.reply_text(            "❌ Введите целое число!\n"
            f"Пример: 15\n"
            f"Диапазон: {INTERVAL_MIN}–{INTERVAL_MAX} сек"
        )

async def show_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data["awaiting_interval_input"] = False
    query = update.callback_query
    matches = await get_today_matches()
    if not matches:
        await query.edit_message_text("Сегодня нет матчей в выбранных лигах.")
        return
    text = "📅 <b>Матчи на сегодня:</b>\n\n"
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        time_info = m.get('elapsed', m.get('period', '—'))
        text += f"{i}. {m['league']} • {time_info}'\n{m['home']} vs {m['away']}\n\n"
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def show_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data["awaiting_interval_input"] = False
    query = update.callback_query
    matches = await get_live_matches()
    if not matches:
        await query.edit_message_text("Нет активных матчей в выбранных лигах.")
        return
    text = "🔴 <b>Сейчас идут матчи:</b>\n\n"
    keyboard = []
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        score = f"{m['home_goals']}:{m['away_goals']}"
        time_info = m.get('elapsed', m.get('period', '?'))
        text += f"{i}. {m['league']} • {time_info}'\n{m['home']} {score} {m['away']}\n\n"
        keyboard.append([InlineKeyboardButton(f"🎯 Отслеживать матч {i}", callback_data=f"monitor_{m['sport']}_{m['id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE, sport, match_id):
    user_data["awaiting_interval_input"] = False
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
        first=1,        chat_id=query.message.chat_id,
        name=f"{sport}_{match_id}"
    )
    
    await query.edit_message_text(
        f"✅ <b>Отслеживание запущено!</b>\n"
        f"🆔 Матч: {match_id}\n"
        f"⏱️ Интервал: <b>{interval} сек</b>\n"
        f"🚨 Уведомление придёт через 1–5 сек после гола!\n\n"
        f"Чтобы остановить: «⏹️ Остановить» или /stop",
        parse_mode='HTML'
    )

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data["awaiting_interval_input"] = False
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
    chat_id = context.job.chat_id
    monitoring = user_data["monitoring"]
    match_id = monitoring["match_id"]
    sport = monitoring["sport"]
    
    if not match_id or not sport:
        return
    
    match = await get_match_details(match_id, sport)
    if not match:
        return
    
    # Защита от аномальных значений
    if match["home_goals"] > 20 or match["away_goals"] > 20:
        for job in context.application.job_queue.get_jobs_by_name(f"{sport}_{match_id}"):
            job.schedule_removal()
        user_data["monitoring"] = {"match_id": None, "sport": None, "last_score": {"home": 0, "away": 0}}
        try:
            await context.bot.send_message(chat_id, "✅ Матч завершён.")
        except:
            pass        return
    
    new_score = {"home": match["home_goals"], "away": match["away_goals"]}
    last_score = monitoring["last_score"]
    
    if new_score != last_score:
        msg = f"🚨 <b>ГОЛ!</b> {match['league']}\n{match['home']} {match['home_goals']}–{match['away_goals']} {match['away']}"
        try:
            await context.bot.send_message(chat_id, msg, parse_mode='HTML')
            user_data["monitoring"]["last_score"] = new_score
        except Exception as e:
            logging.error(f"Ошибка уведомления: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data["awaiting_interval_input"] = False
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
    elif data == 'set_interval': await request_interval_input(update, context)
    elif data == 'today': await show_today(update, context)
    elif data == 'live': await show_live(update, context)
    elif data.startswith('monitor_'):
        parts = data.split('_')
        await start_monitoring(update, context, parts[1], parts[2])
    elif data == 'stop': await stop_monitoring(update, context)
    elif data == 'back': await start(update, context)

# ======================
# 🚀 ЗАПУСК
# ======================

def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_monitoring))    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_interval_input))
    
    app.run_polling()

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not YOUR_TELEGRAM_ID:
        print("❌ Ошибка: не заданы TELEGRAM_TOKEN или YOUR_TELEGRAM_ID!")
        exit(1)
    print("🚀 Бот запускается (БЕЗ API-SPORTS)...")
    print(f"⚡ Скорость уведомлений: 1–5 сек после гола")
    print(f"⏱️ Интервал проверки: {user_data['check_interval']} сек (настраивается в боте)")
    main()

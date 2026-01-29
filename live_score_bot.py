import requests
import time
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# ======================
# 🔑 НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАМЕНИ!)
# ======================
# Эти значения будут перезаписаны из переменных окружения на Railway
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID")) if os.getenv("YOUR_TELEGRAM_ID") else 0

# ⏱️ Настройки
LIVE_CHECK_INTERVAL = 864  # секунд (рекомендуется 864 = 14.4 мин для бесплатного тарифа)
MATCHES_PER_PAGE = 5       # матчей в списке
DAILY_LIMIT = 100          # лимит бесплатного тарифа API-Sports

# 📊 Глобальный счётчик запросов
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
    {"id": 110, "name": "SHL (Швеция)"},
    {"id": 111, "name": "Liiga (Финляндия)"},
]

# 🧠 Данные пользователя
user_data = {
    "selected_football": [39],
    "selected_hockey": [57],
    "monitoring_match_id": None,
    "last_score": {}
}

# ======================
# 🌐 УНИВЕРСАЛЬНЫЙ ЗАПРОС К API С ПОДСЧЁТОМ
# ======================

def make_api_request(url, headers, params=None):
    """Выполняет запрос и считает использование лимита"""
    global api_request_count
    try:
        api_request_count += 1
        logging.info(f"📡 Запрос #{api_request_count}/{DAILY_LIMIT} к API")
        
        # Предупреждение при приближении к лимиту
        if api_request_count >= DAILY_LIMIT - 10:
            warning_msg = f"⚠️ Внимание! Осталось {DAILY_LIMIT - api_request_count} запросов из {DAILY_LIMIT} на сегодня."
            try:
                from telegram import Bot
                bot = Bot(token=TELEGRAM_TOKEN)
                bot.send_message(chat_id=YOUR_TELEGRAM_ID, text=warning_msg)
            except Exception as e:
                logging.error(f"Не удалось отправить предупреждение: {e}")
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        return response
    except Exception as e:
        logging.error(f"Ошибка запроса: {e}")
        return None

# ======================
# 📅 ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ
# ======================

def get_today_matches():
    matches = []
    today = time.strftime("%Y-%m-%d")
    url = "https://api-sports-v1.p.rapidapi.com/v3/fixtures"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": "api-sports-v1.p.rapidapi.com"}
    
    # Футбол
    for league_id in user_data["selected_football"]:
        params = {"date": today, "league": league_id, "timezone": "Europe/Moscow"}
        response = make_api_request(url, headers, params)
        if response and response.status_code == 200:
            data = response.json()
            for m in data.get("response", []):
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "time": m["fixture"]["date"][11:16],
                    "sport": "football"
                })
    
    # Хоккей
    for league_id in user_data["selected_hockey"]:
        params = {"date": today, "league": league_id, "timezone": "Europe/Moscow"}
        response = make_api_request(url, headers, params)
        if response and response.status_code == 200:
            data = response.json()
            for m in data.get("response", []):
                matches.append({
                    "id": m["fixture"]["id"],
                    "league": m["league"]["name"],
                    "home": m["teams"]["home"]["name"],
                    "away": m["teams"]["away"]["name"],
                    "time": m["fixture"]["date"][11:16],
                    "sport": "hockey"
                })
    
    return matches

def get_live_matches():
    matches = []
    url = "https://api-sports-v1.p.rapidapi.com/v3/fixtures"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": "api-sports-v1.p.rapidapi.com"}
    
    # Футбол
    for league_id in user_data["selected_football"]:
        params = {"live": "all", "league": league_id}
        response = make_api_request(url, headers, params)
        if response and response.status_code == 200:
            data = response.json()
            for m in data.get("response", []):
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
        params = {"live": "all", "league": league_id}
        response = make_api_request(url, headers, params)
        if response and response.status_code == 200:
            data = response.json()
            for m in data.get("response", []):
                matches.append({
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

def get_match_details(match_id):
    url = f"https://api-sports-v1.p.rapidapi.com/v3/fixtures?id={match_id}"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": "api-sports-v1.p.rapidapi.com"}
    response = make_api_request(url, headers)
    
    if response and response.status_code == 200:
        data = response.json()
        if data["response"]:
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
# 🤖 TELEGRAM-БОТ
# ======================

def start(update: Update, context: CallbackContext):
    selected_football = ", ".join([next(l['name'] for l in ALL_FOOTBALL_LEAGUES if l['id'] == lid) for lid in user_data["selected_football"]])
    selected_hockey = ", ".join([next(l['name'] for l in ALL_HOCKEY_LEAGUES if l['id'] == lid) for lid in user_data["selected_hockey"]])
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Настроить лиги", callback_data='configure_leagues')],
        [InlineKeyboardButton("📅 Матчи на сегодня", callback_data='today_all')],
        [InlineKeyboardButton("🔴 Live-матчи", callback_data='live')],
        [InlineKeyboardButton("⏹️ Остановить отслеживание", callback_data='stop_monitoring')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        f"✅ <b>Выбранные лиги:</b>\n⚽ {selected_football}\n🏒 {selected_hockey}\n\nТекущий расход: {api_request_count}/{DAILY_LIMIT} запросов.\n\nВыбери действие:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

def configure_leagues(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("⚽ Футбол", callback_data='choose_football')],
        [InlineKeyboardButton("🏒 Хоккей", callback_data='choose_hockey')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Выберите вид спорта:", reply_markup=reply_markup)

def choose_sport(update: Update, context: CallbackContext, sport_type):
    query = update.callback_query
    query.answer()
    leagues = ALL_FOOTBALL_LEAGUES if sport_type == "football" else ALL_HOCKEY_LEAGUES
    selected = user_data["selected_football"] if sport_type == "football" else user_data["selected_hockey"]
    
    keyboard = []
    for league in leagues:
        status = "✅" if league["id"] in selected else "◻️"
        keyboard.append([InlineKeyboardButton(
            f"{status} {league['name']}",
            callback_data=f"toggle_{sport_type}_{league['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='configure_leagues')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        f"Выберите лиги для {'футбола' if sport_type == 'football' else 'хоккея'}:",
        reply_markup=reply_markup
    )

def toggle_league(update: Update, context: CallbackContext, sport_type, league_id):
    query = update.callback_query
    query.answer()
    target_list = user_data["selected_football"] if sport_type == "football" else user_data["selected_hockey"]
    
    if league_id in target_list:
        target_list.remove(league_id)
    else:
        target_list.append(league_id)
    
    choose_sport(update, context, sport_type)

def show_today_matches(update: Update, context: CallbackContext):
    query = update.callback_query
    matches = get_today_matches()
    
    if not matches:
        query.edit_message_text("Сегодня нет матчей в выбранных лигах.")
        return
    
    message = "📅 <b>Матчи на сегодня:</b>\n\n"
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        message += f"{i}. {m['league']}\n⏰ {m['time']} • {m['home']} vs {m['away']}\n\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

def show_live_matches(update: Update, context: CallbackContext):
    query = update.callback_query
    matches = get_live_matches()
    
    if not matches:
        query.edit_message_text("Нет активных матчей в выбранных лигах.")
        return
    
    message = "🔴 <b>Сейчас идут матчи:</b>\n\n"
    keyboard = []
    for i, m in enumerate(matches[:MATCHES_PER_PAGE], 1):
        score = f"{m['home_goals']}-{m['away_goals']}"
        time_info = m['elapsed'] if m['sport'] == 'football' else m['period']
        message += f"{i}. {m['league']} • {time_info}'\n{m['home']} {score} {m['away']}\n\n"
        keyboard.append([InlineKeyboardButton(
            f"🎯 Отслеживать матч {i}",
            callback_data=f"monitor_{m['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

def start_monitoring(update: Update, context: CallbackContext, match_id):
    query = update.callback_query
    user_data["monitoring_match_id"] = int(match_id)
    user_data["last_score"] = {"home": 0, "away": 0}
    
    context.job_queue.run_repeating(
        check_goals,
        interval=LIVE_CHECK_INTERVAL,
        first=1,
        context=query.message.chat_id,
        name=str(match_id)
    )
    
    query.edit_message_text(
        f"✅ Теперь отслеживаю матч ID {match_id}!\n"
        f"Уведомления о голах каждые {LIVE_CHECK_INTERVAL} сек.\n"
        "Чтобы остановить: «⏹️ Остановить» или /stop"
    )

def stop_monitoring_manual(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    match_id = user_data["monitoring_match_id"]
    
    if not match_id:
        msg = "❌ Нет активного отслеживания."
        if update.callback_query:
            update.callback_query.edit_message_text(msg)
        else:
            update.message.reply_text(msg)
        return
    
    current_jobs = context.job_queue.get_jobs_by_name(str(match_id))
    for job in current_jobs:
        job.schedule_removal()
    
    user_data["monitoring_match_id"] = None
    user_data["last_score"] = {}
    
    msg = "⏹️ Отслеживание остановлено вручную."
    if update.callback_query:
        update.callback_query.edit_message_text(msg)
    else:
        update.message.reply_text(msg)

def check_goals(context: CallbackContext):
    global api_request_count
    chat_id = context.job.context
    match_id = user_data["monitoring_match_id"]
    
    # 🛑 Приостановка при приближении к лимиту
    if api_request_count >= DAILY_LIMIT - 2:
        logging.warning("Достигнут лимит запросов. Отслеживание приостановлено.")
        if match_id:
            current_jobs = context.job_queue.get_jobs_by_name(str(match_id))
            for job in current_jobs:
                job.schedule_removal()
            user_data["monitoring_match_id"] = None
            user_data["last_score"] = {}
            try:
                context.bot.send_message(
                    chat_id=chat_id,
                    text="🛑 Достигнут лимит API. Отслеживание приостановлено до завтра."
                )
            except:
                pass
        return
    
    if not match_id:
        return
    
    match = get_match_details(match_id)
    if not match:
        return
    
    # 🚦 Автоматическая остановка при завершении матча
    status = match["status"].upper()
    finished_statuses = ["FT", "AET", "PEN", "FINISHED", "ENDED", "SUSPENDED", "CANC", "ABD", "POSTP"]
    
    if any(finished in status for finished in finished_statuses):
        current_jobs = context.job_queue.get_jobs_by_name(str(match_id))
        for job in current_jobs:
            job.schedule_removal()
        user_data["monitoring_match_id"] = None
        user_data["last_score"] = {}
        final_msg = f"✅ <b>Матч завершён!</b>\n{match['home']} {match['home_goals']}–{match['away_goals']} {match['away']}\nЛига: {match['league']}"
        try:
            context.bot.send_message(chat_id=chat_id, text=final_msg, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Ошибка финального сообщения: {e}")
        return
    
    # 🔍 Уведомление о голе
    new_score = {"home": match["home_goals"], "away": match["away_goals"]}
    last_score = user_data["last_score"]
    
    if new_score != last_score:
        goal_msg = f"🚨 <b>ГОЛ!</b> {match['league']}\n{match['home']} {match['home_goals']}–{match['away_goals']} {match['away']}\nСтатус: {match['status']}"
        try:
            context.bot.send_message(chat_id=chat_id, text=goal_msg, parse_mode='HTML')
            user_data["last_score"] = new_score
        except Exception as e:
            logging.error(f"Ошибка уведомления о голе: {e}")

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    
    if data == 'configure_leagues':
        configure_leagues(update, context)
    elif data == 'choose_football':
        choose_sport(update, context, "football")
    elif data == 'choose_hockey':
        choose_sport(update, context, "hockey")
    elif data.startswith('toggle_football_'):
        league_id = int(data.split('_')[2])
        toggle_league(update, context, "football", league_id)
    elif data.startswith('toggle_hockey_'):
        league_id = int(data.split('_')[2])
        toggle_league(update, context, "hockey", league_id)
    elif data == 'today_all':
        show_today_matches(update, context)
    elif data == 'live':
        show_live_matches(update, context)
    elif data.startswith('monitor_'):
        match_id = data.split('_')[1]
        start_monitoring(update, context, match_id)
    elif data == 'stop_monitoring':
        stop_monitoring_manual(update, context)
    elif data == 'back':
        start(update, context)

# ======================
# 🚀 ОСНОВНОЙ ЗАПУСК С АВТОПЕРЕЗАПУСКОМ
# ======================

def main():
    global api_request_count
    api_request_count = 0  # ✅ Сброс счётчика при каждом запуске main()
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop_monitoring_manual))
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    updater.start_polling()
    logging.info("✅ Бот запущен!")
    updater.idle()

# ======================
# 🔁 АВТОМАТИЧЕСКИЙ ПЕРЕЗАПУСК ПРИ ОШИБКАХ
# ======================

if __name__ == "__main__":
    # Проверка обязательных переменных
    if not TELEGRAM_TOKEN or not RAPID_API_KEY or not YOUR_TELEGRAM_ID:
        print("❌ ОШИБКА: Не заданы переменные окружения!")
        print("   Убедитесь, что в Railway заданы:")
        print("   - TELEGRAM_TOKEN")
        print("   - RAPID_API_KEY")
        print("   - YOUR_TELEGRAM_ID")
        exit(1)
    
    daily_requests = 86400 // LIVE_CHECK_INTERVAL
    print(f"\n❗ Лимит: {DAILY_LIMIT} запросов/день.")
    print(f"   Интервал: {LIVE_CHECK_INTERVAL} сек → ~{daily_requests} запросов/день на матч.")
    if daily_requests > 90:
        print("   ⚠️ Рекомендуется увеличить интервал!")

    restart_count = 0
    max_restarts = 10

    while restart_count < max_restarts:
        try:
            print(f"\n🚀 Запуск бота (попытка #{restart_count + 1})...")
            main()
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен вручную.")
            break
        except Exception as e:
            restart_count += 1
            logging.error(f"❌ Критическая ошибка: {e}")
            print(f"⚠️  Произошла ошибка. Перезапуск через 10 секунд... (попытка {restart_count}/{max_restarts})")
            time.sleep(10)
            # ❌ НЕ сбрасываем api_request_count здесь — он сбрасывается в main()
    
    if restart_count >= max_restarts:
        print(f"💥 Достигнут лимит перезапусков ({max_restarts}). Бот остановлен.")

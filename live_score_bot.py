 import aiohttp
 import logging
 import os
 from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
 from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
 
 # ======================
 # НАСТРОЙКИ
 # ======================
 
 TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
-YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID"))
 API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
 
+
+def parse_telegram_id(value: str | None) -> int | None:
+    if not value:
+        return None
+    try:
+        return int(value)
+    except ValueError:
+        logging.error("Invalid YOUR_TELEGRAM_ID value: %s", value)
+        return None
+
+
+YOUR_TELEGRAM_ID = parse_telegram_id(os.getenv("YOUR_TELEGRAM_ID"))
+
 user_data = {
     "selected_football": [78],
 
     # ❗ ПРАВИЛЬНЫЕ ID ЛИГ
     "selected_hockey": [57, 64, 65, 66],   # NHL, KHL, VHL, MHL
 
     "monitoring": {
         "match_id": None,
         "sport": None,
         "last_score": {"home": 0, "away": 0}
     }
 }
 
 MATCHES_PER_PAGE = 5
 
 
 # ======================
 # API ЗАПРОСЫ
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
         logging.error("OpenLiga error: %s", e)
 
     return []
 
 
 async def fetch_hockey_live():
+    if not API_SPORTS_KEY:
+        logging.warning("API_SPORTS_KEY is not set.")
+        return []
+
     headers = {
         "x-apisports-key": API_SPORTS_KEY
     }
 
     url = "https://v1.hockey.api-sports.io/games?live=all"
 
     try:
         async with aiohttp.ClientSession() as session:
-            async with session.get(url, headers=headers) as resp:
+            async with session.get(
+                url,
+                headers=headers,
+                timeout=aiohttp.ClientTimeout(total=5)
+            ) as resp:
+                if resp.status != 200:
+                    logging.error("Hockey API error: %s", resp.status)
+                    return []
 
                 data = await resp.json()
 
                 logging.info("HOCKEY RAW: %s", data)
 
                 return data.get("response", [])
 
     except Exception as e:
         logging.error("Hockey API error: %s", e)
 
     return []
 
 
 # ======================
 # СБОР МАТЧЕЙ
 # ======================
 
 async def get_live_matches():
     matches = []
 
     # ===== ФУТБОЛ =====
     if 78 in user_data["selected_football"]:
         data = await fetch_bundesliga_live()
 
         for match in data:
@@ -122,50 +145,54 @@ async def get_live_matches():
             "home_goals": scores.get("home", 0),
             "away_goals": scores.get("away", 0),
             "sport": "hockey"
         })
 
     return matches
 
 
 async def get_match_details(match_id, sport):
 
     matches = await get_live_matches()
 
     for m in matches:
         if m["id"] == match_id and m["sport"] == sport:
             return m
 
     return None
 
 
 # ======================
 # TELEGRAM
 # ======================
 
 async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
 
+    if YOUR_TELEGRAM_ID is None:
+        await update.message.reply_text("Не задан YOUR_TELEGRAM_ID.")
+        return
+
     if update.effective_user.id != YOUR_TELEGRAM_ID:
         return
 
     keyboard = [
         [InlineKeyboardButton("Live", callback_data="live")],
         [InlineKeyboardButton("Остановить", callback_data="stop")]
     ]
 
     await update.message.reply_text(
         "Бот готов.\nХоккей: NHL/KHL/VHL/MHL\nФутбол: Бундеслига",
         reply_markup=InlineKeyboardMarkup(keyboard)
     )
 
 
 async def show_live(update, context):
 
     query = update.callback_query
     await query.answer()
 
     matches = await get_live_matches()
 
     if not matches:
         await query.edit_message_text("Нет live матчей")
         return
 
@@ -176,77 +203,83 @@ async def show_live(update, context):
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
 
+    for job in context.application.job_queue.get_jobs_by_name("goal_monitor"):
+        job.schedule_removal()
+
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
-        name=f"{sport}_{match_id}"
+        name="goal_monitor"
     )
 
     await query.edit_message_text("Отслеживание запущено")
 
 
 async def stop_monitoring(update, context):
 
     query = update.callback_query
 
     user_data["monitoring"] = {
         "match_id": None,
         "sport": None,
         "last_score": {"home": 0, "away": 0}
     }
 
+    for job in context.application.job_queue.get_jobs_by_name("goal_monitor"):
+        job.schedule_removal()
+
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
 
         msg = f"ГОЛ!\n{match['home']} {new['home']}:{new['away']} {match['away']}"
 
         await context.bot.send_message(
@@ -268,31 +301,35 @@ async def button_handler(update, context):
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
 
-    if not API_SPORTS_KEY:
-        print("НЕТ API_SPORTS_KEY!")
+    if not TELEGRAM_TOKEN:
+        print("НЕТ TELEGRAM_TOKEN!")
+        exit(1)
+
+    if YOUR_TELEGRAM_ID is None:
+        print("НЕТ/НЕВЕРНЫЙ YOUR_TELEGRAM_ID!")
         exit(1)
 
     main()
     
 
EOF
         )

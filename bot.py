import os
import logging
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import pytz
import datetime

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for webhook
app = Flask(__name__)

# Bot application (PTB 20+ way)
application = Application.builder().token(TOKEN).build()

# Timezone for Gaza
GAZA_TZ = pytz.timezone("Asia/Gaza")

# Game Data
current_question = None
correct_answer = None
first_correct_user = None
answered_users = set()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I'm your English Gameshow Bot on Render!")


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return "Bot is running!"


async def heartbeat_task(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(GAZA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"✅ Bot Heartbeat - Bot is Running.\n⏰ {now}")


def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
    application.bot.set_webhook(url=webhook_url)


async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, correct_answer, first_correct_user, answered_users

    current_question = "What is the capital of France?"
    options = ["Berlin", "Paris", "Madrid", "Rome"]
    correct_answer = "Paris"
    first_correct_user = None
    answered_users.clear()

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 New Question:\n{current_question}", reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global first_correct_user

    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("You've already answered this question!")
        return

    answered_users.add(user_id)

    selected_answer = query.data

    if selected_answer == correct_answer:
        if first_correct_user is None:
            first_correct_user = user_name
        await query.edit_message_text(
            text=f"✅ Correct Answer: {correct_answer}\n🏆 First Correct Answer By: {first_correct_user}\n\nExplanation: Paris is the capital of France."
        )
    else:
        await query.answer("❌ Incorrect. You cannot answer again.")


def schedule_jobs(app: Application):
    app.job_queue.run_daily(send_question, time=datetime.time(hour=8, minute=0, tzinfo=GAZA_TZ))
    app.job_queue.run_daily(send_question, time=datetime.time(hour=12, minute=0, tzinfo=GAZA_TZ))
    app.job_queue.run_daily(send_question, time=datetime.time(hour=17, minute=46, tzinfo=GAZA_TZ))

    app.job_queue.run_repeating(heartbeat_task, interval=60, first=10)


def main():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    schedule_jobs(application)

    set_webhook()

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()

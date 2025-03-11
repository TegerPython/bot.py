import json
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask, request
import asyncio

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "123456"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Flask App for Render Webhook
app = Flask(__name__)

# Global Application (PTB) and Scheduler
application = Application.builder().token(BOT_TOKEN).build()
scheduler = AsyncIOScheduler()

# In-memory data (questions & leaderboard)
questions = []
leaderboard = {}

# Load Questions & Leaderboard
def load_data():
    global questions, leaderboard
    try:
        questions = requests.get(QUESTIONS_JSON_URL).json()
        leaderboard = requests.get(LEADERBOARD_JSON_URL).json()
    except Exception as e:
        logger.error(f"Error loading data: {e}")

# Save Leaderboard
def save_leaderboard():
    try:
        url = LEADERBOARD_JSON_URL.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json"
        }
        data = json.dumps(leaderboard, indent=2)
        response = requests.put(url, headers=headers, data=data)
        logger.info(f"Leaderboard saved: {response.status_code}")
    except Exception as e:
        logger.error(f"Error saving leaderboard: {e}")

# Post Question
async def post_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        logger.warning("No questions left!")
        return

    question = questions.pop(0)
    keyboard = [
        [InlineKeyboardButton(option, callback_data=option)]
        for option in question["options"]
    ]
    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question["question"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.chat_data["current_question"] = question
    context.chat_data["question_message_id"] = message.message_id
    context.chat_data["answered_users"] = set()

# Handle Answer
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    question = context.chat_data.get("current_question")
    if not question:
        await query.message.edit_text("No active question.")
        return

    user = update.effective_user
    correct_answer = question["answer"]

    # Check if user already answered
    if user.id in context.chat_data.get("answered_users", set()):
        await query.message.reply_text(f"{user.first_name}, you already answered!")
        return

    context.chat_data.setdefault("answered_users", set()).add(user.id)

    if query.data == correct_answer:
        leaderboard[user.id] = leaderboard.get(user.id, 0) + 1
        await query.message.reply_text(f"✅ Correct, {user.first_name}!")
    else:
        await query.message.reply_text(f"❌ Incorrect, {user.first_name}. The correct answer was {correct_answer}.")

    save_leaderboard()

# Show Leaderboard
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Leaderboard 🏆\n\n"
    for user_id, score in sorted_leaderboard:
        try:
            user = await context.bot.get_chat(user_id)
            user_name = user.first_name
        except Exception:
            user_name = "Unknown User"

        text += f"{user_name}: {score}\n"
    await update.message.reply_text(text)

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the Quiz Bot!")

# Flask Webhook Handler
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "OK"

# Set Webhook
async def set_webhook():
    await application.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    logger.info(f"Webhook set to: {WEBHOOK_URL}/webhook")

# Initialize Bot and Start Scheduler
async def start_bot():
    load_data()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(button))

    scheduler.add_job(post_question, "cron", hour=8, minute=0, day_of_week="*")
    scheduler.add_job(post_question, "cron", hour=12, minute=0, day_of_week="*")
    scheduler.add_job(post_question, "cron", hour=18, minute=0, day_of_week="*")

    scheduler.start()
    
    await application.initialize()
    await set_webhook()
    await application.run_polling()
    await application.shutdown()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(start_bot())

    # Start Flask app (Render Hosting)
    app.run(host="0.0.0.0", port=8443)
    

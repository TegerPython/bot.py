import os
import json
import asyncio
import logging
from datetime import time
from flask import Flask, request
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
PORT = int(os.getenv("PORT", 5000))  # ✅ Use Render's PORT

# Flask app for webhook
flask_app = Flask(__name__)

# Telegram bot application
bot_app = Application.builder().token(TOKEN).build()

# Scheduler for posting questions
scheduler = AsyncIOScheduler()

# Load questions from GitHub
def fetch_questions():
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching questions: {e}")
        return []

# Load leaderboard from GitHub
def fetch_leaderboard():
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching leaderboard: {e}")
        return {}

# Save leaderboard to GitHub (Mock function)
def save_leaderboard(leaderboard):
    # TODO: Implement GitHub API update logic
    pass

async def post_question(context: ContextTypes.DEFAULT_TYPE):
    """Post a question to the Telegram channel."""
    questions = fetch_questions()
    if not questions:
        return

    question = questions.pop(0)  # Get first question
    options = question["options"]
    correct_answer = question["answer"]

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=json.dumps({"q": question["id"], "a": i}))]
        for i, opt in enumerate(options)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID, text=question["question"], reply_markup=reply_markup
    )

    # Store correct answer mapping
    context.bot_data[question["id"]] = {"correct": correct_answer, "msg_id": message.message_id}

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user responses to questions."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    question_id, selected_answer = data["q"], data["a"]

    correct_answer = context.bot_data.get(question_id, {}).get("correct")
    if correct_answer is None:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name

    if selected_answer == correct_answer:
        response = f"✅ {username} answered correctly!"
        # Update leaderboard
        leaderboard = fetch_leaderboard()
        leaderboard[user_id] = leaderboard.get(user_id, 0) + 1
        save_leaderboard(leaderboard)
    else:
        response = f"❌ {username} answered incorrectly."

    await query.edit_message_text(text=response)

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Post the current leaderboard."""
    leaderboard = fetch_leaderboard()
    if not leaderboard:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="No scores yet!")
        return

    sorted_scores = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "\n".join([f"{i+1}. {user_id}: {score}" for i, (user_id, score) in enumerate(sorted_scores)])

    await context.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 Leaderboard:\n\n{leaderboard_text}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command for the bot."""
    await update.message.reply_text("Hello! I'm your quiz bot!")

# Add handlers to the bot
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CallbackQueryHandler(handle_answer))

# Flask route for webhook
@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming Telegram updates."""
    update = Update.de_json(request.get_json(), bot_app.bot)
    asyncio.create_task(bot_app.process_update(update))
    return "OK", 200

async def run():
    """Run the bot with webhook."""
    await bot_app.initialize()
    await bot_app.bot.set_webhook(WEBHOOK_URL)
    
    # Start Flask server with Render's PORT
    flask_app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    # Schedule jobs properly
    scheduler.add_job(post_question, "cron", hour=8, minute=0, args=[bot_app])
    scheduler.add_job(post_question, "cron", hour=12, minute=0, args=[bot_app])
    scheduler.add_job(post_question, "cron", hour=18, minute=0, args=[bot_app])
    scheduler.add_job(post_leaderboard, "cron", hour=20, minute=0, args=[bot_app])
    
    scheduler.start()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        scheduler.shutdown()

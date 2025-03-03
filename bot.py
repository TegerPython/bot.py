import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import json
import random
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Load from environment variables
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # New - Your public Render URL like https://my-bot.onrender.com/webhook
PORT = int(os.getenv("PORT", 8443))  # Default to 8443 for Telegram webhooks, Render can also use 10000

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables to hold questions and leaderboard
questions = []
leaderboard = {}

# Load questions and leaderboard data
def load_data():
    global questions, leaderboard
    try:
        with open("questions.json", "r") as f:
            questions = json.load(f)
        with open("leaderboard.json", "r") as f:
            leaderboard = json.load(f)
        logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.warning(f"Could not load data: {e}")

# Save leaderboard data
def save_leaderboard():
    with open("leaderboard.json", "w") as f:
        json.dump(leaderboard, f, indent=4)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the English Challenge Bot!")

# Send question to channel
async def send_question():
    if not questions:
        logger.warning("No questions available.")
        return

    question = random.choice(questions)
    message_text = f"❓ *Question:* {question['question']}\n\n"
    options = question['options']

    keyboard = []
    for idx, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"{question['id']}|{idx}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    # Store the correct answer
    question['correct_index'] = question['correct']
    question['message_id'] = message.message_id

# Handle button presses (user answers)
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    question_id, selected_option_index = query.data.split("|")
    selected_option_index = int(selected_option_index)

    # Find question
    question = next((q for q in questions if q['id'] == question_id), None)
    if not question:
        await query.edit_message_text("⚠️ Error: Question not found.")
        return

    correct_index = question['correct_index']
    user = query.from_user

    if str(user.id) in question.get('answered_users', []):
        await query.answer("You've already answered this question!", show_alert=True)
        return

    question.setdefault('answered_users', []).append(str(user.id))

    if selected_option_index == correct_index:
        # Correct
        text = f"✅ Correct! {user.first_name} got it right."
        leaderboard[str(user.id)] = leaderboard.get(str(user.id), 0) + 1
        save_leaderboard()
    else:
        # Incorrect
        text = f"❌ Incorrect. Better luck next time, {user.first_name}!"

    await query.edit_message_text(text)

# Command to show leaderboard
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaderboard_text = "🏆 *Leaderboard:*\n\n"
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    for user_id, score in sorted_leaderboard[:10]:
        user = await context.bot.get_chat(user_id)
        leaderboard_text += f"{user.first_name}: {score} points\n"

    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

# Manual test question command
async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_question()

# Scheduler for automatic questions
scheduler = BackgroundScheduler()

def start_scheduler(application):
    scheduler.add_job(lambda: application.create_task(send_question()), 'cron', hour=8, minute=0)
    scheduler.add_job(lambda: application.create_task(send_question()), 'cron', hour=12, minute=0)
    scheduler.add_job(lambda: application.create_task(send_question()), 'cron', hour=18, minute=0)
    scheduler.start()

# Main function to start bot
def main():
    load_data()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(button))

    start_scheduler(application)

    if WEBHOOK_URL:
        logger.info(f"Starting bot in webhook mode at: {WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL
        )
    else:
        logger.warning("WEBHOOK_URL not set, starting in polling mode.")
        application.run_polling()

if __name__ == "__main__":
    main()

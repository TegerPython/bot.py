import os
import logging
import json
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import weekly_leaderboard
import leaderboard
import requests

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
APP_NAME = os.getenv("RENDER_APP_NAME") # or RENDER_URL without the https:// part.
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")
QUESTIONS_URL = os.getenv("QUESTIONS_JSON_URL") # Add this line
WEEKLY_QUESTIONS_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL") # Add this line

# Global variables
weekly_questions = []

def load_questions_from_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error loading questions from {url}: {e}")
        return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Bot is running."
    )

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers
    weekly_poll_message_ids = []
    weekly_user_answers = {}
    for i, question in enumerate(weekly_questions):
        try:
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=5,  # 5 seconds for testing
            )
            weekly_poll_message_ids.append(message.message_id)
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll
    user_id = update.effective_user.id
    if poll.is_closed:
        return
    if user_id not in weekly_user_answers:
        weekly_user_answers[user_id] = {"correct_answers": 0, "username": update.effective_user.first_name}
    for option in poll.options:
        if option.voter_count > 0 and poll.options.index(option) == poll.correct_option_id:
            weekly_user_answers[user_id]["correct_answers"] += 1
            leaderboard.update_score(user_id, 1)
            weekly_leaderboard.update_weekly_score(user_id, 1)
            break

async def send_weekly_results(context: ContextTypes.DEFAULT_TYPE):
    weekly_leaderboard_data = weekly_leaderboard.load_weekly_leaderboard()
    results = sorted(weekly_leaderboard_data.items(), key=lambda item: item[1], reverse=True)
    message = "🏆 Weekly Quiz Results 🏆\n\n"
    if results:
        for i, (user_id, score) in enumerate(results):
            user = await context.bot.get_chat(user_id)
            if i == 0:
                message += f"🥇 {user.first_name} 🥇: {score} points\n\n"
            elif i == 1:
                message += f"🥈 {user.first_name} 🥈: {score} points\n"
            elif i == 2:
                message += f"🥉 {user.first_name} 🥉: {score} points\n"
            else:
                message += f"{user.first_name}: {score} points\n"
    else:
        message += "No participants."
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global weekly_questions
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    weekly_leaderboard.reset_weekly_leaderboard()
    weekly_questions = load_questions_from_url(WEEKLY_QUESTIONS_URL) # Load questions from URL
    if not weekly_questions:
        await update.message.reply_text("❌ Failed to load weekly questions.")
        return
    await send_weekly_questionnaire(context)
    await send_weekly_results(context)

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received update: {update}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("testweekly", test_weekly))
    application.add_handler(CallbackQueryHandler(handle_weekly_poll_answer))
    application.add_handler(MessageHandler(filters.ALL, handle_update))

    PORT = int(os.environ.get("PORT", "5000"))
    logger.info(f"Starting bot on port {PORT}")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}",
        secret_token=TELEGRAM_SECRET_TOKEN
    )

if __name__ == "__main__":
    main()

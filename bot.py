import os
import json
import random
import logging
import datetime
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from telegram.ext import ApplicationBuilder

# Environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")

# Global storage
questions = []
leaderboard = {}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_github_file(url):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text

async def load_data():
    global questions, leaderboard
    try:
        questions_json = await fetch_github_file(QUESTIONS_JSON_URL)
        questions = json.loads(questions_json)
        logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")

    try:
        leaderboard_json = await fetch_github_file(LEADERBOARD_JSON_URL)
        leaderboard = json.loads(leaderboard_json)
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        logger.warning("No questions available to send.")
        return

    question = random.choice(questions)
    questions.remove(question)

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"{question['id']}|{opt}")]
        for opt in question["options"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = f"🔔 New Question!\n\n{question['question']}"
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    question_id, selected_option = data.split('|')

    if user_id in context.bot_data.get('answered_users', {}).get(question_id, []):
        await query.edit_message_text("❌ You've already answered this question.")
        return

    correct_option = None
    for q in questions:
        if q["id"] == question_id:
            correct_option = q["answer"]
            explanation = q.get("explanation", "")
            break

    context.bot_data.setdefault('answered_users', {}).setdefault(question_id, []).append(user_id)

    if selected_option == correct_option:
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        message = f"✅ Correct! {query.from_user.first_name} got it right.\n\n{explanation}"
    else:
        message = f"❌ Wrong answer, {query.from_user.first_name}. The correct answer was: {correct_option}\n\n{explanation}"

    await query.edit_message_text(message)

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "\n".join([f"{index + 1}. {await context.bot.get_chat(int(user)).first_name}: {score}"
                                   for index, (user, score) in enumerate(sorted_leaderboard[:10])])
    await update.message.reply_text(f"🏆 Leaderboard:\n\n{leaderboard_text}")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running and webhook is set!")

async def set_webhook(application):
    url = f"{WEBHOOK_URL}"
    success = await application.bot.set_webhook(url)
    if success:
        logger.info(f"Webhook set successfully: {url}")
    else:
        logger.error(f"Failed to set webhook: {url}")

def setup_jobs(application):
    job_queue = application.job_queue

    job_queue.run_daily(send_question, time=datetime.time(hour=8, minute=0))
    job_queue.run_daily(send_question, time=datetime.time(hour=12, minute=0))
    job_queue.run_daily(send_question, time=datetime.time(hour=18, minute=0))

async def main():
    await load_data()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CallbackQueryHandler(button_callback))

    setup_jobs(application)

    # Set webhook once on startup
    await set_webhook(application)

    logger.info("Starting application with webhook mode...")

    # Use async start for webhook (correct Render-compatible way)
    runner = application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )
    await runner

if __name__ == "__main__":
    asyncio.run(main())

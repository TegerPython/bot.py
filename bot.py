import os
import json
import datetime
import asyncio
import logging
import httpx
from telegram import (
    Update, 
    Poll, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    PollAnswerHandler, 
    ApplicationBuilder
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurations from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "744871903"))

# Initialize data storage
questions = []
leaderboard = {}
current_poll = {}

# Fetch JSON from GitHub
async def fetch_json_from_github(url):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch JSON from GitHub: {e}")
        return None

# Load data at startup
async def load_data():
    global questions, leaderboard
    questions = await fetch_json_from_github(QUESTIONS_JSON_URL) or []
    leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL) or {}

# Send poll question
async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll

    if not questions:
        logger.warning("No questions available.")
        return

    question_data = questions.pop(0)

    poll_message = await context.bot.send_poll(
        chat_id=CHANNEL_ID,
        question=question_data['question'],
        options=question_data['options'],
        type=Poll.QUIZ,
        is_anonymous=True,
        correct_option_id=question_data['correct_option_id'],
        explanation=question_data.get('explanation', '')
    )

    current_poll = {
        "message_id": poll_message.message_id,
        "correct_option_id": question_data['correct_option_id'],
        "answered_users": {}
    }

    await update_questions_on_github()

async def update_questions_on_github():
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
            url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/questions.json"

            content = json.dumps(questions, indent=2).encode('utf-8')
            response = await client.get(url, headers=headers)
            sha = response.json().get("sha")

            data = {
                "message": "Update questions.json",
                "content": content.decode('utf-8').encode('base64').decode('utf-8'),
                "sha": sha
            }

            await client.put(url, headers=headers, json=data)
    except Exception as e:
        logger.error(f"Failed to update questions.json: {e}")

# Poll answer handler
async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.poll_answer.user
    user_id = str(user.id)

    if user_id in current_poll['answered_users']:
        return  # Ignore repeat answers

    selected_option = update.poll_answer.option_ids[0]
    current_poll['answered_users'][user_id] = selected_option

    if selected_option == current_poll['correct_option_id']:
        username = user.username or user.first_name or str(user_id)
        leaderboard[username] = leaderboard.get(username, 0) + 1

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"✅ {username} answered correctly first!"
        )
        await update_leaderboard_on_github()

async def update_leaderboard_on_github():
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
            url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/leaderboard.json"

            content = json.dumps(leaderboard, indent=2).encode('utf-8')
            response = await client.get(url, headers=headers)
            sha = response.json().get("sha")

            data = {
                "message": "Update leaderboard.json",
                "content": content.decode('utf-8').encode('base64').decode('utf-8'),
                "sha": sha
            }

            await client.put(url, headers=headers, json=data)
    except Exception as e:
        logger.error(f"Failed to update leaderboard.json: {e}")

# Leaderboard command
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)

    if not leaderboard:
        await update.message.reply_text("🏆 No leaderboard data available.")
        return

    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 Leaderboard:\n"

    for rank, (user, score) in enumerate(sorted_leaderboard, start=1):
        leaderboard_text += f"{rank}. {user}: {score} points\n"

    await update.message.reply_text(leaderboard_text)

# Test command
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_TELEGRAM_ID:
        return

    await update.message.reply_text("✅ Bot is running fine!")

# Setup jobs
def setup_jobs(application: Application):
    scheduler = AsyncIOScheduler()

    scheduler.add_job(send_question, CronTrigger(hour=8, minute=0), args=[application])
    scheduler.add_job(send_question, CronTrigger(hour=12, minute=0), args=[application])
    scheduler.add_job(send_question, CronTrigger(hour=18, minute=0), args=[application])

    scheduler.start()

# Main
async def main():
    await load_data()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(PollAnswerHandler(handle_poll_answer))

    setup_jobs(application)

    webhook_url = f"{WEBHOOK_URL}"
    logger.info(f"Setting webhook URL: {webhook_url}")
    await application.bot.set_webhook(url=webhook_url)

    logger.info("Starting application with webhook mode...")
    await application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    asyncio.run(main())

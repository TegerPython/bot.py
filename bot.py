import os
import json
import datetime
import random
import asyncio
import logging
import httpx
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackContext
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Data Storage
questions = []
leaderboard = {}

# Load Questions
async def load_questions():
    global questions
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(QUESTIONS_JSON_URL)
            questions = response.json()
            logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")

# Load Leaderboard
async def load_leaderboard():
    global leaderboard
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(LEADERBOARD_JSON_URL)
            leaderboard = response.json()
            logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}

# Save Leaderboard to GitHub
async def save_leaderboard():
    content = json.dumps(leaderboard, indent=4)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/leaderboard.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        async with httpx.AsyncClient() as client:
            get_response = await client.get(url, headers=headers)
            sha = get_response.json().get('sha', '')

            data = {
                "message": "Update leaderboard",
                "content": content.encode('utf-8').decode('latin1').encode('base64').decode(),
                "sha": sha
            }

            put_response = await client.put(url, headers=headers, json=data)
            if put_response.status_code == 200 or put_response.status_code == 201:
                logger.info("Leaderboard successfully saved to GitHub.")
            else:
                logger.error(f"Failed to save leaderboard: {put_response.text}")
    except Exception as e:
        logger.error(f"Error saving leaderboard: {e}")

# Send Question to Channel
async def send_question(context: CallbackContext):
    if not questions:
        logger.warning("No questions available.")
        return

    question = questions.pop(0)

    keyboard = [
        [InlineKeyboardButton(option, callback_data=str(i))]
        for i, option in enumerate(question['options'])
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 New Question!\n\n{question['question']}",
        reply_markup=reply_markup
    )

    context.job_queue.run_once(
        lambda ctx: reveal_answer(ctx, message.message_id, question),
        when=60,
        chat_id=CHANNEL_ID
    )

async def reveal_answer(context: CallbackContext, message_id: int, question):
    correct_option = question['correct_option']
    explanation = question.get('explanation', '')

    answer_text = f"✅ Correct Answer: {question['options'][correct_option]}"
    if explanation:
        answer_text += f"\n\nℹ️ Explanation: {explanation}"

    await context.bot.edit_message_text(
        chat_id=CHANNEL_ID,
        message_id=message_id,
        text=f"{context.job.data['original_text']}\n\n{answer_text}"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm the Quiz Bot!")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.full_name

    if user_id in leaderboard:
        await query.answer("You've already answered this question.")
        return

    selected_option = int(query.data)

    question = context.chat_data.get('current_question')
    correct_option = question['correct_option']

    if selected_option == correct_option:
        leaderboard[user_id] = leaderboard.get(user_id, 0) + 1
        await query.answer("🎉 Correct!")
    else:
        await query.answer("❌ Wrong answer.")

    await save_leaderboard()

def setup_jobs(application: Application):
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time=datetime.time(hour=8, minute=0, second=0))
    job_queue.run_daily(send_question, time=datetime.time(hour=12, minute=0, second=0))
    job_queue.run_daily(send_question, time=datetime.time(hour=18, minute=0, second=0))

async def main():
    await load_questions()
    await load_leaderboard()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))

    setup_jobs(application)

    port = int(os.getenv("PORT", 10000))
    webhook_url = os.getenv("WEBHOOK_URL", "https://bot-py-dcpa.onrender.com/webhook")

    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set successfully: {webhook_url}")

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    logging.info("Starting bot...")
    asyncio.run(main())

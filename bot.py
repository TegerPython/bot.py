import os
import json
import random
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ContextTypes,
)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
RENDER_URL = os.getenv("RENDER_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")
REPO_OWNER = os.getenv("REPO_OWNER")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

questions = []
leaderboard = {}

# Load questions and leaderboard
def load_questions_and_leaderboard():
    global questions, leaderboard
    try:
        import requests
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        
        # Load questions
        response = requests.get(QUESTIONS_JSON_URL, headers=headers)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} questions")

        # Load leaderboard
        response = requests.get(LEADERBOARD_JSON_URL, headers=headers)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load data: {e}")

# Save leaderboard back to GitHub
def save_leaderboard():
    try:
        import requests
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/leaderboard.json"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        sha = response.json()["sha"]

        content = json.dumps(leaderboard, indent=4)
        encoded_content = content.encode("utf-8").decode("latin1")

        data = {
            "message": "Update leaderboard",
            "content": encoded_content.encode("utf-8").decode("latin1"),
            "sha": sha
        }

        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info("Leaderboard saved successfully")
    except Exception as e:
        logger.error(f"Could not save leaderboard: {e}")

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the English Quiz Bot!")

# Test command handler
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Bot is working!")

# Send question to the channel
async def send_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    global questions
    if not questions:
        logger.warning("No questions left to send.")
        return

    question = questions.pop(0)
    question_text = question['question']
    options = question['options']
    correct_option_id = question['correct_option_id']

    poll_message = await context.bot.send_poll(
        chat_id=CHANNEL_ID,
        question=question_text,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_option_id,
        explanation=question.get('explanation', "No explanation provided.")
    )

    context.chat_data['current_poll'] = {
        "message_id": poll_message.message_id,
        "correct_option_id": correct_option_id,
        "answered_users": []
    }

    save_questions_to_github()

# Save remaining questions to GitHub
def save_questions_to_github():
    try:
        import requests
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/questions.json"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        sha = response.json()["sha"]

        content = json.dumps(questions, indent=4)
        encoded_content = content.encode("utf-8").decode("latin1")

        data = {
            "message": "Update questions",
            "content": encoded_content.encode("utf-8").decode("latin1"),
            "sha": sha
        }

        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info("Questions saved successfully")
    except Exception as e:
        logger.error(f"Could not save questions: {e}")

# Button callback handler
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text=f"Selected option: {query.data}")

# Poll answer handler
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    poll_id = update.poll_answer.poll_id
    user_id = update.poll_answer.user.id

    poll_data = context.chat_data.get('current_poll', {})

    if user_id in poll_data.get('answered_users', []):
        return

    poll_data['answered_users'].append(user_id)

    if update.poll_answer.option_ids[0] == poll_data['correct_option_id']:
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        save_leaderboard()

# Schedule question posting
def setup_jobs(application: Application):
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time=datetime.time(8, 0))
    job_queue.run_daily(send_question, time=datetime.time(12, 0))
    job_queue.run_daily(send_question, time=datetime.time(18, 0))

# Main function
async def main():
    load_questions_and_leaderboard()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('test', test))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    setup_jobs(application)

    port = int(os.getenv("PORT", 10000))
    webhook_url = WEBHOOK_URL

    logger.info(f"Setting webhook to: {webhook_url}")
    await application.bot.set_webhook(webhook_url)

    await application.start()
    await application.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="/webhook",
        webhook_url=webhook_url,
    )

    logger.info(f"Bot running on port {port} with webhook {webhook_url}")
    await application.updater.wait_for_stop()
    await application.stop()

if __name__ == '__main__':
    asyncio.run(main())

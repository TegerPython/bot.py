import os
import logging
import asyncio
import json
import datetime
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
import httpx

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Global state
questions = []
leaderboard = {}
current_question = None
current_correct_option = None
answered_users = set()


async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def load_questions():
    global questions
    try:
        questions = await fetch_data(QUESTIONS_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")
        questions = []


async def load_leaderboard():
    global leaderboard
    try:
        leaderboard = await fetch_data(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}


async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, current_correct_option, answered_users

    if not questions:
        logger.warning("No questions available")
        return

    question = questions.pop(0)
    current_question = question
    current_correct_option = question['correct_option']
    answered_users = set()

    poll_message = await context.bot.send_poll(
        chat_id=CHANNEL_ID,
        question=question['question'],
        options=question['options'],
        is_anonymous=False,
        allows_multiple_answers=False
    )

    question['message_id'] = poll_message.message_id
    await update_questions_json()


async def update_questions_json():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/questions.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        file_data = response.json()
        sha = file_data['sha']

        updated_questions_json = json.dumps(questions, indent=2)

        data = {
            "message": "Update questions.json",
            "content": updated_questions_json.encode("utf-8").decode("latin1"),
            "sha": sha
        }

        response = await client.put(url, headers=headers, json=data)
        response.raise_for_status()


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id

    if user_id in answered_users:
        return

    answered_users.add(user_id)

    if poll_answer.option_ids[0] == current_correct_option:
        username = update.poll_answer.user.first_name
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎉 {username} answered correctly!"
        )
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        await update_leaderboard_json()


async def update_leaderboard_json():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/leaderboard.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        file_data = response.json()
        sha = file_data['sha']

        updated_leaderboard_json = json.dumps(leaderboard, indent=2)

        data = {
            "message": "Update leaderboard.json",
            "content": updated_leaderboard_json.encode("utf-8").decode("latin1"),
            "sha": sha
        }

        response = await client.put(url, headers=headers, json=data)
        response.raise_for_status()


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running!")


def setup_jobs(application):
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time=datetime.time(8, 0))
    job_queue.run_daily(send_question, time=datetime.time(12, 0))
    job_queue.run_daily(send_question, time=datetime.time(18, 0))


async def main():
    await load_questions()
    await load_leaderboard()

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    setup_jobs(application)

    logger.info("Starting application with webhook mode...")

    await application.bot.set_webhook(f"{WEBHOOK_URL}")

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook"
    )


if __name__ == "__main__":
    asyncio.run(main())

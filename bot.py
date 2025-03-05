import os
import json
import random
import logging
import asyncio
import datetime
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.daily import DailyTrigger

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")

logging.basicConfig(
    format='%(levelname)s:%(name)s:%(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

questions = []
leaderboard = {}
answered_users = set()


async def fetch_github_file(url: str) -> dict:
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_github_file(QUESTIONS_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")

    try:
        leaderboard = await fetch_github_file(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}


async def save_leaderboard():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/leaderboard.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    current_content = json.dumps(leaderboard, indent=4)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        sha = response.json()["sha"]

        data = {
            "message": "Update leaderboard",
            "content": current_content.encode('utf-8').decode('latin1'),
            "sha": sha
        }

        await client.put(url, headers=headers, json=data)


async def send_question(context: CallbackContext):
    global answered_users
    if not questions:
        await load_data()

    if not questions:
        logger.warning("No questions available.")
        return

    question = random.choice(questions)
    questions.remove(question)

    answered_users.clear()

    options = question["options"]
    correct_option = question["correct_option"]

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"answer_{i}")]
        for i, opt in enumerate(options)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    question_text = f"❓ {question['question']}"
    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question_text,
        reply_markup=reply_markup
    )

    context.job_queue.run_once(
        reveal_answer, 3600,  # 1 hour later
        data={
            "message_id": message.message_id,
            "correct_option": correct_option,
            "question": question
        }
    )

    await save_questions()


async def reveal_answer(context: CallbackContext):
    data = context.job.data
    correct_option = data["correct_option"]
    message_id = data["message_id"]
    question = data["question"]

    text = f"✅ Correct answer: {question['options'][correct_option]}\n\n"
    if answered_users:
        first_correct_user = list(answered_users)[0]
        text += f"🏆 First correct answer by: {first_correct_user}\n"
    else:
        text += "😔 No correct answers received.\n"

    await context.bot.edit_message_text(
        chat_id=CHANNEL_ID,
        message_id=message_id,
        text=text
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name
    option_selected = int(query.data.split("_")[1])

    if user_id in answered_users:
        await query.answer("You've already answered this question.")
        return

    data = context.job_queue.jobs()[0].data
    correct_option = data["correct_option"]

    if option_selected == correct_option:
        answered_users.add(user_name)
        leaderboard[user_name] = leaderboard.get(user_name, 0) + 1
        await query.answer("✅ Correct!")
        await save_leaderboard()
    else:
        await query.answer("❌ Wrong answer. Better luck next time!")

    await query.edit_message_reply_markup(reply_markup=None)


async def save_questions():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/questions.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    current_content = json.dumps(questions, indent=4)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        sha = response.json()["sha"]

        data = {
            "message": "Update questions",
            "content": current_content.encode('utf-8').decode('latin1'),
            "sha": sha
        }

        await client.put(url, headers=headers, json=data)


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏅 Leaderboard 🏅\n\n"
    for rank, (user, score) in enumerate(sorted_leaderboard[:10], 1):
        leaderboard_text += f"{rank}. {user} - {score} points\n"

    await update.message.reply_text(leaderboard_text)


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) == OWNER_TELEGRAM_ID:
        await send_question(context)
        await update.message.reply_text("Test question sent.")
    else:
        await update.message.reply_text("❌ You are not authorized.")


def setup_handlers(application: Application):
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CallbackQueryHandler(button))


def setup_jobs(application: Application):
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time=datetime.time(hour=8))
    job_queue.run_daily(send_question, time=datetime.time(hour=12))
    job_queue.run_daily(send_question, time=datetime.time(hour=18))


async def main():
    application = Application.builder().token(TOKEN).build()

    setup_handlers(application)
    setup_jobs(application)

    await load_data()

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()


if __name__ == "__main__":
    asyncio.run(main())

import os
import json
import logging
import random
import asyncio
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll, PollOption
)
from telegram.ext import (
    Application, CommandHandler, CallbackContext, CallbackQueryHandler,
    PollAnswerHandler, ContextTypes
)
import httpx

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")
RENDER_URL = os.getenv("RENDER_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
PORT = int(os.getenv("PORT", 8080))

# Question/Leaderboard storage
questions = []
leaderboard = {}

async def fetch_json_from_github(url: str):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Could not load {url}: {e}")
            return None

async def save_json_to_github(url: str, data):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    file_path = url.replace(f"https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/main/", "")
    file_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"

    async with httpx.AsyncClient() as client:
        response = await client.get(file_url, headers=headers)
        response.raise_for_status()
        file_data = response.json()
        sha = file_data.get("sha")

        update_data = {
            "message": "Update JSON file",
            "content": json.dumps(data, indent=4).encode("utf-8").decode("latin1").encode("base64").decode(),
            "sha": sha
        }

        response = await client.put(file_url, headers=headers, json=update_data)
        response.raise_for_status()

async def load_data():
    global questions, leaderboard
    questions = await fetch_json_from_github(QUESTIONS_JSON_URL) or []
    leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL) or {}

async def update_leaderboard():
    await save_json_to_github(LEADERBOARD_JSON_URL, leaderboard)

async def update_questions():
    await save_json_to_github(QUESTIONS_JSON_URL, questions)

async def send_question(context: CallbackContext):
    global questions
    if not questions:
        await load_data()
        if not questions:
            logger.warning("No questions available.")
            return

    question = questions.pop(0)
    await update_questions()

    if question["type"] == "poll":
        message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.REGULAR,
            allows_multiple_answers=False,
            is_anonymous=False
        )
        context.bot_data[message.poll.id] = {
            "correct_option": question["correct_option"],
            "first_correct": None
        }
    elif question["type"] == "buttons":
        buttons = [
            [InlineKeyboardButton(opt, callback_data=f"ans:{idx}")]
            for idx, opt in enumerate(question["options"])
        ]
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=question["question"],
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        context.bot_data[message.message_id] = {
            "correct_option": question["correct_option"],
            "first_correct": None
        }

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    message_id = query.message.message_id
    user_id = query.from_user.id

    if message_id not in context.bot_data:
        await query.message.edit_text("This question has expired.")
        return

    data = context.bot_data[message_id]
    correct_option = data["correct_option"]

    if user_id in data.get("answered_users", set()):
        await query.message.reply_text("You already answered this question.")
        return

    data.setdefault("answered_users", set()).add(user_id)

    selected_option = int(query.data.split(":")[1])
    if selected_option == correct_option:
        if data["first_correct"] is None:
            data["first_correct"] = user_id
            leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
            await update_leaderboard()

        await query.message.edit_text(f"✅ Correct!\n\nWinner: {query.from_user.first_name}")
    else:
        await query.message.edit_text("❌ Wrong answer.")

async def poll_answer_handler(update: Update, context: CallbackContext):
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id

    if poll_id not in context.bot_data:
        return

    data = context.bot_data[poll_id]
    correct_option = data["correct_option"]

    if user_id in data.get("answered_users", set()):
        return

    data.setdefault("answered_users", set()).add(user_id)

    if poll_answer.option_ids[0] == correct_option:
        if data["first_correct"] is None:
            data["first_correct"] = user_id
            leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
            await update_leaderboard()

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome to the English Competition Bot!")

async def test(update: Update, context: CallbackContext):
    await send_question(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^ans:\d+$"))
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    application.job_queue.run_daily(send_question, time=datetime.time(hour=8, minute=0))
    application.job_queue.run_daily(send_question, time=datetime.time(hour=12, minute=0))
    application.job_queue.run_daily(send_question, time=datetime.time(hour=18, minute=0))

    webhook_url = f"{RENDER_URL}/webhook"
    logger.info(f"🔗 Attempting to set webhook to: {webhook_url}")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook",
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    import datetime
    import base64
    import sys

    if sys.version_info < (3, 9):
        base64.encode = lambda s: base64.b64encode(s).decode()
    else:
        base64.encode = lambda s: base64.b64encode(s.encode()).decode()

    asyncio.run(load_data())
    main()

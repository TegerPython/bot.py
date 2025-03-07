import os
import json
import base64
import datetime
import logging
import asyncio
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
import httpx

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)  # Fixed: Use __name__

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")

# In-memory storage
questions = []
leaderboard = {}
current_poll_id = None
current_correct_option_id = None  # Store correct answer
answered_users = set()

async def fetch_json_from_github(url):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

async def upload_json_to_github(file_path, data, message):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient() as client:
        # Get current file SHA if exists
        sha = None
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                sha = response.json().get("sha")
        except httpx.HTTPStatusError:
            pass

        # Prepare content
        content = json.dumps(data, indent=4).encode('utf-8')
        encoded_content = base64.b64encode(content).decode('utf-8')  # Fixed encoding

        payload = {
            "message": message,
            "content": encoded_content,
            "sha": sha
        }

        response = await client.put(url, headers=headers, json=payload)
        response.raise_for_status()

async def load_data():
    global questions, leaderboard
    questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
    leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
    logger.info(f"Loaded {len(questions)} questions")
    logger.info(f"Loaded {len(leaderboard)} leaderboard entries")

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, current_correct_option_id, answered_users

    if not questions:
        logger.warning("No questions left to send!")
        return

    question_data = questions.pop(0)
    poll_message = await context.bot.send_poll(
        chat_id=CHANNEL_ID,
        question=question_data['question'],
        options=question_data['options'],
        type=Poll.QUIZ,
        correct_option_id=question_data['correct_option_id'],
        explanation=question_data.get('explanation', '')
    )

    # Store poll information
    current_poll_id = poll_message.poll.id
    current_correct_option_id = question_data['correct_option_id']  # Store correct answer
    answered_users = set()

    await upload_json_to_github("questions.json", questions, "Remove used question")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users, leaderboard, current_correct_option_id

    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    username = update.effective_user.username or update.effective_user.first_name

    if poll_answer.poll_id != current_poll_id:
        return

    if user_id in answered_users:
        logger.info(f"User {username} already answered.")
        return

    answered_users.add(user_id)

    # Use stored correct answer
    if poll_answer.option_ids[0] == current_correct_option_id:
        logger.info(f"User {username} answered correctly!")

        # Update leaderboard
        if username not in leaderboard:
            leaderboard[username] = 0
        leaderboard[username] += 1  # Fixed indentation

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎉 {username} answered correctly first!"
        )
        await upload_json_to_github("leaderboard.json", leaderboard, "Update leaderboard")

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 Leaderboard:\n"
    for rank, (user, score) in enumerate(sorted_leaderboard, start=1):
        leaderboard_text += f"{rank}. {user}: {score} point{'s' if score != 1 else ''}\n"
    
    await context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

def setup_jobs(application):
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time=datetime.time(8, 0))
    job_queue.run_daily(send_question, time=datetime.time(12, 0))
    job_queue.run_daily(send_question, time=datetime.time(18, 0))
    job_queue.run_daily(post_leaderboard, time=datetime.time(19, 0))

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running!")

async def main():
    await load_data()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    setup_jobs(application)

    PORT = int(os.getenv("PORT", "10000"))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        url_path="",
        drop_pending_updates=True
    )

if __name__ == "__main__":  # Fixed main guard
    asyncio.run(main())

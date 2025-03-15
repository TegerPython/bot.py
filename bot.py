import os
import json
import datetime
import logging
import asyncio
import base64
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
import httpx

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
answered_users = set()
polls_data = {}

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
        # Get current SHA
        response = await client.get(url, headers=headers)
        sha = response.json().get("sha") if response.status_code == 200 else None

        # Prepare content
        content = json.dumps(data, indent=4).encode('utf-8')
        base64_content = base64.b64encode(content).decode('utf-8')

        payload = {
            "message": message,
            "content": base64_content,
            "sha": sha
        }

        response = await client.put(url, headers=headers, json=payload)
        response.raise_for_status()

async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
        leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
        logger.info(f"Data loaded: {len(questions)} questions, {len(leaderboard)} scores")
    except Exception as e:
        logger.error(f"Data load failed: {e}")

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users, polls_data

    if not questions:
        logger.warning("No questions available")
        return

    try:
        question_data = questions.pop(0)
        poll = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question_data['question'],
            options=question_data['options'],
            type=Poll.QUIZ,
            correct_option_id=question_data['correct_option_id'],
            explanation=question_data.get('explanation', '')
        )
        
        current_poll_id = poll.poll.id
        answered_users = set()
        polls_data[current_poll_id] = poll.poll
        
        await upload_json_to_github("questions.json", questions, "Question used")
    except Exception as e:
        logger.error(f"Failed to send question: {e}")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global leaderboard

    answer = update.poll_answer
    user_id = answer.user.id
    username = update.effective_user.username or update.effective_user.first_name

    if answer.poll_id != current_poll_id:
        return

    if user_id in answered_users:
        logger.info(f"Duplicate answer from {username}")
        return

    answered_users.add(user_id)

    poll = polls_data.get(answer.poll_id)
    if not poll:
        logger.warning("Poll data missing")
        return

    if answer.option_ids[0] == poll.correct_option_id:
        leaderboard[username] = leaderboard.get(username, 0) + 1
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎉 {username} answered correctly first!"
        )
        await upload_json_to_github("leaderboard.json", leaderboard, "Score update")

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Leaderboard:\n" + "\n".join(
        f"{i}. {user}: {score}" for i, (user, score) in enumerate(sorted_board, 1)
    )
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

def setup_jobs(app):
    tz = datetime.timezone(datetime.timedelta(hours=3))  # Adjust to your timezone
    times = [datetime.time(8, 0), datetime.time(12, 0), datetime.time(18, 0)]
    
    for time in times:
        app.job_queue.run_daily(send_question, time=time, days=tuple(range(7)), timezone=tz)
    
    app.job_queue.run_daily(post_leaderboard, datetime.time(19, 0), days=tuple(range(7)), timezone=tz)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot operational")

async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    
    await load_data()
    setup_jobs(application)

    PORT = int(os.getenv("PORT", 8443))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Server starting on port {PORT}")

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        url_path="webhook"
    )

if __name__ == "__main__":
    asyncio.run(main())

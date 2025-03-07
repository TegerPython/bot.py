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
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 744871903))

# In-memory storage
questions = []
leaderboard = {}
current_poll_id = None
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
        # Get current file SHA
        try:
            get_response = await client.get(url, headers=headers)
            sha = get_response.json().get("sha") if get_response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error getting file SHA: {e}")
            return False

        # Prepare content
        content = json.dumps(data, indent=2)
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        payload = {
            "message": message,
            "content": encoded_content,
            "sha": sha
        }

        try:
            put_response = await client.put(url, headers=headers, json=payload)
            put_response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False

async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
        leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        questions = []
        leaderboard = {}

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users

    if not questions:
        logger.warning("No questions available!")
        return

    try:
        question_data = questions.pop(0)
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question_data['question'],
            options=question_data['options'],
            type=Poll.QUIZ,
            is_anonymous=True,  # Required for channel polls
            correct_option_id=question_data['correct_option_id'],
            explanation=question_data.get('explanation', '')
        )

        current_poll_id = poll_message.poll.id
        answered_users = set()

        # Update GitHub questions
        if await upload_json_to_github("questions.json", questions, "Remove used question"):
            logger.info("Successfully updated questions.json")
        else:
            logger.error("Failed to update questions.json")

    except Exception as e:
        logger.error(f"Error sending question: {e}")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users, leaderboard

    poll_answer = update.poll_answer
    if poll_answer.poll_id != current_poll_id:
        return

    user_id = poll_answer.user.id
    username = poll_answer.user.username or poll_answer.user.first_name

    if user_id in answered_users:
        logger.info(f"User {username} already answered")
        return

    answered_users.add(user_id)

    try:
        # Update leaderboard
        leaderboard[str(user_id)] = {
            "username": username,
            "score": leaderboard.get(str(user_id), {}).get("score", 0) + 1
        }

        # Update GitHub leaderboard
        if await upload_json_to_github("leaderboard.json", leaderboard, "Update leaderboard"):
            logger.info(f"Updated leaderboard for {username}")
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🎉 {username} answered correctly! Total points: {leaderboard[str(user_id)]['score']}"
            )
        else:
            logger.error("Failed to update leaderboard")

    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    try:
        sorted_leaderboard = sorted(
            leaderboard.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

        leaderboard_text = "🏆 Weekly Leaderboard:\n"
        for rank, (user_id, data) in enumerate(sorted_leaderboard[:10], 1):
            leaderboard_text += f"{rank}. {data['username']}: {data['score']} points\n"

        await context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)
    except Exception as e:
        logger.error(f"Error posting leaderboard: {e}")

async def send_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text="❤️ Bot heartbeat - System operational")
        await context.bot.send_message(chat_id=OWNER_ID, text=f"📊 Status: {len(questions)} questions left | {len(leaderboard)} players")
    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔️ Unauthorized")
        return

    try:
        await send_question(context)
        await update.message.reply_text("✅ Test question sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending test question: {e}")

def setup_jobs(application):
    job_queue = application.job_queue
    
    # Daily questions
    job_queue.run_daily(send_question, time=datetime.time(8, 0))
    job_queue.run_daily(send_question, time=datetime.time(12, 0))
    job_queue.run_daily(send_question, time=datetime.time(18, 0))
    
    # Daily leaderboard
    job_queue.run_daily(post_leaderboard, time=datetime.time(19, 0))
    
    # Heartbeat every minute
    job_queue.run_repeating(send_heartbeat, interval=60, first=10)

async def main():
    await load_data()

    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    
    setup_jobs(application)

    PORT = int(os.getenv("PORT", 8443))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)
    
    logger.info(f"Bot started on port {PORT} with webhook {WEBHOOK_URL}")
    
    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook"
    )

if __name__ == "__main__":
    asyncio.run(main())import os
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
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 744871903))

# In-memory storage
questions = []
leaderboard = {}
current_poll_id = None
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
        # Get current file SHA
        try:
            get_response = await client.get(url, headers=headers)
            sha = get_response.json().get("sha") if get_response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error getting file SHA: {e}")
            return False

        # Prepare content
        content = json.dumps(data, indent=2)
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        payload = {
            "message": message,
            "content": encoded_content,
            "sha": sha
        }

        try:
            put_response = await client.put(url, headers=headers, json=payload)
            put_response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False

async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
        leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        questions = []
        leaderboard = {}

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users

    if not questions:
        logger.warning("No questions available!")
        return

    try:
        question_data = questions.pop(0)
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question_data['question'],
            options=question_data['options'],
            type=Poll.QUIZ,
            is_anonymous=True,  # Required for channel polls
            correct_option_id=question_data['correct_option_id'],
            explanation=question_data.get('explanation', '')
        )

        current_poll_id = poll_message.poll.id
        answered_users = set()

        # Update GitHub questions
        if await upload_json_to_github("questions.json", questions, "Remove used question"):
            logger.info("Successfully updated questions.json")
        else:
            logger.error("Failed to update questions.json")

    except Exception as e:
        logger.error(f"Error sending question: {e}")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users, leaderboard

    poll_answer = update.poll_answer
    if poll_answer.poll_id != current_poll_id:
        return

    user_id = poll_answer.user.id
    username = poll_answer.user.username or poll_answer.user.first_name

    if user_id in answered_users:
        logger.info(f"User {username} already answered")
        return

    answered_users.add(user_id)

    try:
        # Update leaderboard
        leaderboard[str(user_id)] = {
            "username": username,
            "score": leaderboard.get(str(user_id), {}).get("score", 0) + 1
        }

        # Update GitHub leaderboard
        if await upload_json_to_github("leaderboard.json", leaderboard, "Update leaderboard"):
            logger.info(f"Updated leaderboard for {username}")
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🎉 {username} answered correctly! Total points: {leaderboard[str(user_id)]['score']}"
            )
        else:
            logger.error("Failed to update leaderboard")

    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    try:
        sorted_leaderboard = sorted(
            leaderboard.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

        leaderboard_text = "🏆 Weekly Leaderboard:\n"
        for rank, (user_id, data) in enumerate(sorted_leaderboard[:10], 1):
            leaderboard_text += f"{rank}. {data['username']}: {data['score']} points\n"

        await context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)
    except Exception as e:
        logger.error(f"Error posting leaderboard: {e}")

async def send_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text="❤️ Bot heartbeat - System operational")
        await context.bot.send_message(chat_id=OWNER_ID, text=f"📊 Status: {len(questions)} questions left | {len(leaderboard)} players")
    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔️ Unauthorized")
        return

    try:
        await send_question(context)
        await update.message.reply_text("✅ Test question sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending test question: {e}")

def setup_jobs(application):
    job_queue = application.job_queue
    
    # Daily questions
    job_queue.run_daily(send_question, time=datetime.time(8, 0))
    job_queue.run_daily(send_question, time=datetime.time(12, 0))
    job_queue.run_daily(send_question, time=datetime.time(18, 0))
    
    # Daily leaderboard
    job_queue.run_daily(post_leaderboard, time=datetime.time(19, 0))
    
    # Heartbeat every minute
    job_queue.run_repeating(send_heartbeat, interval=60, first=10)

async def main():
    await load_data()

    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    
    setup_jobs(application)

    PORT = int(os.getenv("PORT", 8443))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)
    
    logger.info(f"Bot started on port {PORT} with webhook {WEBHOOK_URL}")
    
    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook"
    )

if __name__ == "__main__":
    asyncio.run(main())

import os
import json
import logging
import random
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
import pytz

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# GitHub Config (Repo storing questions & leaderboard)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # e.g., "your-username/repo-name"
QUESTIONS_FILE = "questions.json"
LEADERBOARD_FILE = "leaderboard.json"

# Global Variables
questions = []
leaderboard = {}
answered_users = set()
current_question = None
current_message_id = None

# GitHub API Headers
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Helper - Fetch File from GitHub
def fetch_github_file(file_name):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}"
    response = requests.get(url, headers=GITHUB_HEADERS)
    if response.status_code == 200:
        content = response.json()["content"]
        return json.loads(requests.utils.unquote(content).encode('ascii'))
    else:
        logger.error(f"Failed to fetch {file_name}: {response.status_code} - {response.text}")
        return None

# Helper - Upload File to GitHub
def upload_github_file(file_name, content, message="Update file"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}"
    existing_file = requests.get(url, headers=GITHUB_HEADERS)
    sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None

    data = {
        "message": message,
        "content": json.dumps(content, indent=2).encode("utf-8").decode("latin1").encode("base64").decode(),
        "sha": sha
    }
    response = requests.put(url, headers=GITHUB_HEADERS, json=data)

    if response.status_code in [200, 201]:
        logger.info(f"Successfully updated {file_name}")
    else:
        logger.error(f"Failed to update {file_name}: {response.status_code} - {response.text}")

# Load Questions and Leaderboard from GitHub
def load_data():
    global questions, leaderboard
    questions = fetch_github_file(QUESTIONS_FILE) or []
    leaderboard = fetch_github_file(LEADERBOARD_FILE) or {}
    logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")

# Save Leaderboard back to GitHub
def save_leaderboard():
    upload_github_file(LEADERBOARD_FILE, leaderboard, "Update leaderboard")

# Send Daily or Test Question
async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> None:
    global current_question, answered_users, current_message_id

    answered_users = set()
    current_question = random.choice(questions) if is_test else questions[datetime.now().day % len(questions)]

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 Daily Challenge:\n\n{current_question['question']}",
        reply_markup=reply_markup
    )
    current_message_id = message.message_id

# Handle Answer Submission
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global answered_users, current_question, current_message_id

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user_id)
    user_answer = query.data
    correct = user_answer == current_question["answer"]

    if correct:
        await query.answer("✅ Correct!")
        leaderboard[username] = leaderboard.get(username, 0) + 1
        save_leaderboard()

        explanation = current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "📝 Daily Challenge (Answered)\n\n"
            f"Question: {current_question['question']}\n"
            f"✅ Correct Answer: {current_question['answer']}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username} (+1 point)"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text=edited_text
            )
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.")

# Show Leaderboard (Private Command)
async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

# Heartbeat Check
async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

# Daily Leaderboard Announcement
async def send_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Daily Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

# Test Command to Trigger Sample Question (Private Command)
async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    await send_question(context, is_test=True)

# Time Helper
def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone(pytz.utc).time()

# Main Function
def main():
    load_data()

    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    application.bot.set_webhook(WEBHOOK_URL)

    job_queue = application.job_queue
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))
    job_queue.run_daily(send_daily_leaderboard, get_utc_time(23, 59, "Asia/Gaza"))
    job_queue.run_repeating(heartbeat, interval=60)

    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))

    application.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT", 8443)), webhook_url=WEBHOOK_URL)

if __name__ == "__main__":
    main()

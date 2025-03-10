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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")

# Global variables
questions = []
leaderboard = {}
current_poll_id = None
answered_users = set()


async def fetch_json_from_github(url):
    """Fetch JSON data from a GitHub repository."""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch {url}: {response.status_code}")
            return {}


async def upload_json_to_github(file_path, data, message):
    """Upload JSON data to GitHub, updating the file."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        sha = response.json().get("sha") if response.status_code == 200 else None

        content = json.dumps(data, indent=4).encode('utf-8')
        encoded_content = base64.b64encode(content).decode('utf-8')

        payload = {
            "message": message,
            "content": encoded_content,
            "sha": sha
        }
        response = await client.put(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            logger.info(f"Updated {file_path} on GitHub")
        else:
            logger.error(f"Failed to update {file_path}: {response.text}")


async def load_data():
    """Load questions and leaderboard data from GitHub."""
    global questions, leaderboard
    questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
    leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
    logger.info(f"Loaded {len(questions)} questions, {len(leaderboard)} leaderboard entries")


async def send_question(context: ContextTypes.DEFAULT_TYPE):
    """Send a quiz question to the Telegram channel."""
    global current_poll_id, answered_users
    if not questions:
        logger.warning("No questions available.")
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
    current_poll_id = poll_message.poll.id
    answered_users = set()

    # Update the questions file
    await upload_json_to_github("questions.json", questions, "Removed used question")


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle answers to the quiz poll."""
    global current_poll_id, answered_users, leaderboard
    answer = update.poll_answer

    if answer.poll_id != current_poll_id or answer.user.id in answered_users:
        return

    answered_users.add(answer.user.id)
    user = update.effective_user.username or update.effective_user.first_name

    correct_option_id = next((poll.poll.correct_option_id for poll in context.bot_data.get("polls", [])
                              if poll.poll.id == current_poll_id), None)

    if correct_option_id is not None and answer.option_ids[0] == correct_option_id:
        leaderboard[user] = leaderboard.get(user, 0) + 1
        await context.bot.send_message(CHANNEL_ID, f"🎉 {user} answered correctly first!")
        await upload_json_to_github("leaderboard.json", leaderboard, "Updated leaderboard")


async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Post the leaderboard to the Telegram channel."""
    sorted_lb = "\n".join(f"{i}. {k}: {v}" for i, (k, v) in enumerate(
        sorted(leaderboard.items(), key=lambda x: x[1], reverse=True), 1))
    await context.bot.send_message(CHANNEL_ID, f"🏆 Leaderboard:\n{sorted_lb}")


def setup_jobs(app):
    """Schedule the daily questions and leaderboard posting."""
    times = [(8, 0), (12, 0), (18, 0), (19, 0)]
    for time in times[:3]:
        app.job_queue.run_daily(send_question, datetime.time(*time))
    app.job_queue.run_daily(post_leaderboard, datetime.time(*times[3]))


async def test(update: Update, _):
    """Confirm bot operation."""
    await update.message.reply_text("✅ Bot operational")


async def main():
    """Main function to start the bot."""
    await load_data()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("test", test))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    setup_jobs(app)

    logger.info("Bot started successfully!")
    await app.run_polling()


# Proper event loop handling for Render
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())

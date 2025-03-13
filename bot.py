import os
import json
import datetime
import logging
import base64
import httpx
import threading
import asyncio
from flask import Flask
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler

# Flask setup
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot operational", 200

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

# In-memory storage
questions = []
leaderboard = {}
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
        response.raise_for_status()

async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
        leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Data loading error: {str(e)}")
        questions = questions if questions else []
        leaderboard = leaderboard if leaderboard else {}

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        logger.warning("No questions left!")
        return

    question_data = questions.pop(0)
    try:
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question_data['question'],
            options=question_data['options'],
            type=Poll.QUIZ,
            correct_option_id=question_data['correct_option_id'],
            explanation=question_data.get('explanation', '')
        )
        
        context.bot_data.setdefault("current_polls", {})[poll_message.poll.id] = {
            "correct_option_id": question_data['correct_option_id'],
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        global answered_users
        answered_users = set()
        
        await upload_json_to_github("questions.json", questions, "Question removed")
        
    except Exception as e:
        logger.error(f"Failed to send question: {str(e)}")
        questions.insert(0, question_data)

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user.id
    username = answer.user.username or answer.user.first_name
    
    poll_info = context.bot_data.get("current_polls", {}).get(answer.poll_id)
    if not poll_info:
        return
    
    if user_id in answered_users:
        return
    
    if answer.option_ids[0] == poll_info['correct_option_id']:
        answered_users.add(user_id)
        leaderboard[username] = leaderboard.get(username, 0) + 1
        
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🏅 {username} got it right first! (+1 point)"
            )
            await upload_json_to_github("leaderboard.json", leaderboard, "Score updated")
        except Exception as e:
            logger.error(f"Failed to update leaderboard: {str(e)}")

async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    if not leaderboard:
        return
    
    leaderboard_text = "🏆 Current Leaderboard:\n"
    sorted_scores = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    for idx, (user, score) in enumerate(sorted_scores, 1):
        leaderboard_text += f"{idx}. {user}: {score} {'point' if score == 1 else 'points'}\n"
    
    try:
        await context.bot.send_message(CHANNEL_ID, leaderboard_text)
    except Exception as e:
        logger.error(f"Failed to post leaderboard: {str(e)}")

def setup_jobs(application):
    times = [(8,0), (12,0), (18,0)]
    for hour, minute in times:
        application.job_queue.run_daily(
            send_question,
            time=datetime.time(hour, minute),
            name=f"daily_question_{hour}h"
        )
    application.job_queue.run_daily(post_leaderboard, time=datetime.time(19, 0))

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot operational!")

async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    
    setup_jobs(application)

    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.getenv("PORT", 8443))
    
    await load_data()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )

def start_flask():
    flask_app.run(host='0.0.0.0', port=8443, use_reloader=False)

if __name__ == '__main__':
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=start_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Run the bot in the main thread
    asyncio.run(run_bot())

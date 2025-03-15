import os
import json
import datetime
import logging
import asyncio
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
import httpx
import base64  # ADDED BACK

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
current_poll_id = None
answered_users = set()
polls_data = {}  # RESTORED CRUCIAL STORAGE

async def fetch_json_from_github(url):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

async def upload_json_to_github(file_path, data, message):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # Get current file SHA
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        sha = response.json().get("sha") if response.status_code == 200 else None

    # Fix encoding
    content = json.dumps(data, indent=4).encode('utf-8')
    base64_content = base64.b64encode(content).decode('utf-8')  # PROPER BASE64

    payload = {
        "message": message,
        "content": base64_content,
        "sha": sha
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=payload)
        response.raise_for_status()

async def load_data():
    global questions, leaderboard
    try:
        questions = await fetch_json_from_github(QUESTIONS_JSON_URL)
        leaderboard = await fetch_json_from_github(LEADERBOARD_JSON_URL)
        logger.info(f"Loaded {len(questions)} questions")
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Failed loading data: {e}")

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_poll_id, answered_users, polls_data

    if not questions:
        logger.warning("No questions left!")
        return

    try:
        question_data = questions.pop(0)
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question_data['question'],
            options=question_data['options'],
            type=Poll.QUIZ,
            correct_option_id=question_data['correct_option_id'],
            explanation=question_data.get('explanation', '')
        )
        
        # Store poll data correctly
        current_poll_id = poll_message.poll.id
        answered_users = set()
        polls_data[current_poll_id] = poll_message.poll  # CRUCIAL FOR ANSWER CHECKING
        
        await upload_json_to_github("questions.json", questions, "Question used")
    except Exception as e:
        logger.error(f"Failed sending question: {e}")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global leaderboard, polls_data

    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    username = update.effective_user.username or update.effective_user.first_name

    # Get correct answer from stored polls
    poll = polls_data.get(poll_answer.poll_id)
    if not poll:
        logger.warning(f"Unknown poll ID: {poll_answer.poll_id}")
        return

    if user_id in answered_users:
        logger.info(f"Duplicate answer from {username}")
        return

    answered_users.add(user_id)

    if poll_answer.option_ids and poll_answer.option_ids[0] == poll.correct_option_id:
        logger.info(f"Correct answer from {username}")
        leaderboard[username] = leaderboard.get(username, 0) + 1
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎉 {username} answered correctly first!"
        )
        await upload_json_to_github("leaderboard.json", leaderboard, "Score update")

# Rest of the code remains identical...
# (post_leaderboard, setup_jobs, test_command, main, etc.)

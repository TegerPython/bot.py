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
        if await upload_json_to_github("questions.json", questions,

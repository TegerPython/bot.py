import json
import logging
import os
import random
import requests
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll)
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, PollAnswerHandler, filters)

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
QUESTIONS_JSON_URL = "https://raw.githubusercontent.com/TegerPython/bot_data/main/questions.json"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global storage
questions = []

async def fetch_questions():
    global questions
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = json.loads(response.text)
        logger.info(f"Loaded {len(questions)} questions.")
    except Exception as e:
        logger.error(f"Failed to fetch questions: {e}")

async def post_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        await fetch_questions()
        if not questions:
            logger.warning("No questions available after fetch.")
            return

    question = questions.pop(0)  # Get the next question
    await update_questions_json()

    if question.get("type") == "poll":
        await send_poll_question(context, question)
    elif question.get("type") == "buttons":
        await send_button_question(context, question)
    else:
        logger.warning(f"Unknown question type: {question.get('type')}")

async def send_poll_question(context, question):
    message = await context.bot.send_poll(
        chat_id=CHANNEL_ID,
        question=question['question'],
        options=question['options'],
        type=Poll.QUIZ,
        correct_option_id=question['correct_option'],
        explanation=question.get('explanation', 'No explanation provided.')
    )
    context.chat_data['current_poll'] = message.poll.id
    context.chat_data['correct_option'] = question['correct_option']

async def send_button_question(context, question):
    buttons = [InlineKeyboardButton(option, callback_data=str(i)) for i, option in enumerate(question['options'])]
    reply_markup = InlineKeyboardMarkup([buttons])
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question['question'],
        reply_markup=reply_markup
    )
    context.chat_data['correct_option'] = question['correct_option']

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    correct_option = context.chat_data.get('correct_option')
    if correct_option is None:
        return

    if int(query.data) == correct_option:
        await query.edit_message_text(f"Correct! ✅")
    else:
        await query.edit_message_text(f"Wrong answer. ❌")

async def update_questions_json():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/questions.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    new_content = json.dumps(questions, indent=2)
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to fetch existing questions.json from GitHub: {response.status_code}")
        return

    sha = response.json().get('sha')
    update_data = {
        "message": "Update questions.json",
        "content": new_content.encode('utf-8').decode('utf-8'),
        "sha": sha
    }

    update_response = requests.put(url, headers=headers, json=update_data)
    if update_response.status_code != 200:
        logger.error(f"Failed to update questions.json: {update_response.status_code}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.job_queue.run_repeating(post_question, interval=86400, first=0)  # Daily question

    application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(fetch_questions())
    main()

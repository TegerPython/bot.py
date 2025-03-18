import os
import logging
import requests
import json
import asyncio
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes
import time

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables (Replace with your actual values)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") #add this line

# Global variables
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []

# Load Weekly Questions from URL
def load_weekly_questions():
    global weekly_questions
    try:
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        response.raise_for_status()
        weekly_questions = response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions from {WEEKLY_QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly questions from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {WEEKLY_QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading weekly questions: {e}")

load_weekly_questions()

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_question_index

    if not weekly_questions:
        logger.error("No weekly questions available.")
        return

    start_index = weekly_question_index * 10
    end_index = min(start_index + 10, len(weekly_questions))

    if start_index >= len(weekly_questions):
        logger.info("All weekly questions have been used. Restarting from the beginning.")
        weekly_question_index = 0
        start_index = 0
        end_index = min(10, len(weekly_questions))

    weekly_poll_message_ids = []

    for i in range(start_index, end_index):
        try:
            question = weekly_questions[i]
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=30  # 30 seconds
            )
            weekly_poll_message_ids.append(message.message_id)
            time.sleep(30)  # Wait for 30 seconds
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

    weekly_question_index += 1  # Increment the index after sending 10 questions
    logger.info(f"weekly_question_index is now: {weekly_question_index}") #debugging line

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_questionnaire(context)

async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("testweekly", test_weekly))

    port = int(os.environ.get("PORT", 5000))  # Get the port from the environment
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}", #use your webhook url here.
    )

if __name__ == "__main__":
    asyncio.run(main())

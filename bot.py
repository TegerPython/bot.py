import json
import os
import logging
import httpx
from telegram import Update, Poll, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Environment Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

current_question = None
answered_users = set()

async def fetch_questions():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(QUESTIONS_JSON_URL)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                return data
            else:
                logger.error("Invalid JSON format")
                return []
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        return []

async def save_questions(questions):
    try:
        headers = {
            "Authorization": f"token {os.getenv('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github.v3+json",
        }
        repo_owner = os.getenv("REPO_OWNER")
        repo_name = os.getenv("REPO_NAME")
        file_path = "questions.json"
        file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"

        response = await httpx.AsyncClient().get(file_url, headers=headers)
        response.raise_for_status()
        sha = response.json()["sha"]

        encoded_content = json.dumps(questions, indent=4).encode("utf-8")
        update_response = await httpx.AsyncClient().put(
            file_url,
            headers=headers,
            json={
                "message": "Update questions.json after using a question",
                "content": encoded_content.decode("utf-8"),
                "sha": sha,
            },
        )
        update_response.raise_for_status()
    except Exception as e:
        logger.error(f"Error saving questions: {e}")

async def send_question(context: CallbackContext):
    global current_question, answered_users

    questions = await fetch_questions()
    if not questions:
        logger.info("No questions left.")
        return

    current_question = questions.pop(0)
    await save_questions(questions)

    answered_users.clear()

    if current_question["type"] == "poll":
        await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=current_question["question"],
            options=current_question["options"],
            type=Poll.QUIZ,
            correct_option_id=current_question["correct_option_id"],
            explanation=current_question["explanation"],
        )
    elif current_question["type"] == "buttons":
        keyboard = [
            [InlineKeyboardButton(option, callback_data=option)] for option in current_question["options"]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=current_question["question"],
            reply_markup=reply_markup,
        )

async def button_callback(update: Update, context: CallbackContext):
    global current_question, answered_users

    query = update.callback_query
    user_id = query.from_user.id

    if user_id in answered_users:
        await query.answer("You've already answered this question!")
        return

    answered_users.add(user_id)
    selected_option = query.data
    correct_option = current_question["correct_option"]

    if selected_option == correct_option:
        await query.answer("✅ Correct!")
    else:
        await query.answer("❌ Wrong answer!")

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Quiz bot is running!")

async def test(update: Update, context: CallbackContext):
    await send_question(context)

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Scheduler for automatic question posting
    scheduler = BackgroundScheduler()

    scheduler.add_job(send_question, CronTrigger(hour=8, minute=0), args=[application.bot])
    scheduler.add_job(send_question, CronTrigger(hour=12, minute=0), args=[application.bot])
    scheduler.add_job(send_question, CronTrigger(hour=18, minute=0), args=[application.bot])

    scheduler.start()

    application.run_webhook(
        listen="0.0.0.0",
        port=443,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
    )

if __name__ == "__main__":
    main()

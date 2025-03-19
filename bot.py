import os
import logging
import time
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables (Replace with your actual values)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))

# Global variables
weekly_questions = [
    {"question": "What is 2+2?", "options": ["3", "4", "5"], "correct_option": 1},
    {"question": "What is the capital of France?", "options": ["Berlin", "London", "Paris"], "correct_option": 2},
    {"question": "What is the largest planet?", "options": ["Earth", "Jupiter", "Mars"], "correct_option": 1},
]
weekly_poll_message_ids = []
weekly_user_answers = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Bot is running."
    )

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers
    weekly_poll_message_ids = []
    weekly_user_answers = {}
    for i, question in enumerate(weekly_questions):
        try:
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=5,  # 5 seconds for testing
            )
            weekly_poll_message_ids.append(message.message_id)
            time.sleep(5)  # Wait for 5 seconds
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")
    await send_weekly_results(context) # direct call, no job queue

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received poll answer: {update.poll.id}") # simplified logging
    # time.sleep(1) # add delay if needed

async def send_weekly_results(context: ContextTypes.DEFAULT_TYPE):
    results = sorted(weekly_user_answers.items(), key=lambda item: item[1]["correct_answers"], reverse=True)
    message = "🏆 Weekly Quiz Results 🏆\n\n"
    if results:
        for i, (user_id, user_data) in enumerate(results):
            if i == 0:
                message += f"🥇 {user_data['username']} 🥇: {user_data['correct_answers']} points\n\n"
            elif i == 1:
                message += f"🥈 {user_data['username']} 🥈: {user_data['correct_answers']} points\n"
            elif i == 2:
                message += f"🥉 {user_data['username']} 🥉: {user_data['correct_answers']} points\n"
            else:
                message += f"{user_data['username']}: {user_data['correct_answers']} points\n"
    else:
        message += "No participants."
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await send_weekly_questionnaire(context)

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received update: {update}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("testweekly", test_weekly))
    application.add_handler(CallbackQueryHandler(handle_weekly_poll_answer))
    application.add_handler(MessageHandler(filters.ALL, handle_update))
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting bot on port {port}")
    application.run_polling()

if __name__ == "__main__":
    main()

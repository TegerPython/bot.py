import asyncio
import logging
import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ Your exact bot token and channel name
TOKEN = "6296032339:AAG-fqxgHLOoI3CNiGFupWvwU0_4zvN6cLc"
CHANNEL = "@TegerTopics"

# Initialize the bot application
app = Application.builder().token(TOKEN).build()

async def start(update: Update, context: CallbackContext) -> None:
    """Send a welcome message when the /start command is issued."""
    await update.message.reply_text("Hello! I am your quiz bot. Stay tuned for questions!")

async def send_question(context: CallbackContext) -> None:
    """Send a quiz question at scheduled times."""
    question_text = "Here's your English quiz question! What is the correct sentence?"
    await context.bot.send_message(chat_id=CHANNEL, text=question_text)

async def post_leaderboard(context: CallbackContext) -> None:
    """Post leaderboard at the scheduled time."""
    leaderboard_text = "🏆 Leaderboard:\n1. User1 - 10 points\n2. User2 - 8 points"
    await context.bot.send_message(chat_id=CHANNEL, text=leaderboard_text)

async def main():
    """Main function to start the bot and schedule jobs."""
    app.add_handler(CommandHandler("start", start))

    # Schedule quiz questions daily at 8 AM, 12 PM, and 6 PM
    question_times = [(8, 0), (12, 0), (18, 0)]
    for time in question_times:
        app.job_queue.run_daily(send_question, datetime.time(*time), days=(0, 1, 2, 3, 4, 5, 6))

    # Schedule the leaderboard at 6:30 PM
    app.job_queue.run_daily(post_leaderboard, datetime.time(18, 30), days=(0, 1, 2, 3, 4, 5, 6))

    logger.info("Bot is running...")

    # Run the bot in polling mode with the correct event loop
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())  # ✅ Fixed event loop issue

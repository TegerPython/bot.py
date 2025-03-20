import os
import logging
import asyncio
from telegram import Update, Poll, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))

async def send_test_poll(context: ContextTypes.DEFAULT_TYPE):
    try:
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question="Test Poll?",
            options=["Yes", "No"],
            type=Poll.QUIZ,
            correct_option_id=0,
            open_period=3,  # 3-second poll
        )
        poll_id = poll_message.poll.id
        await asyncio.sleep(3)  # Wait for poll to close
        poll_results = await context.bot.get_poll(poll_id=poll_id)
        logger.info(f"Poll Results: {poll_results}")
        print(f"Poll Results: {poll_results}") #print to console.
    except Exception as e:
        logger.error(f"Error sending/handling poll: {e}")
        print(f"Error sending/handling poll: {e}") #print to console.

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Test command received from {update.effective_user.id}")
    await send_test_poll(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("testpoll", test_command))
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

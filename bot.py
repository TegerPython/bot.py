import os
import telegram
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info("Starting Telegram API test.")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is not set.")
    print("TELEGRAM_BOT_TOKEN environment variable is not set.")
    exit(1)  # Exit with an error code

try:
    logger.info("Initializing Telegram bot.")
    bot = telegram.Bot(token=BOT_TOKEN)

    logger.info("Getting bot information.")
    bot_info = bot.get_me()
    logger.info(f"Bot information: {bot_info}")
    print(f"Bot information: {bot_info}")

    for i in range(3):
        logger.info(f"Attempting to get updates (attempt {i+1}).")
        updates = bot.get_updates()
        logger.info(f"Updates received (attempt {i+1}): {updates}")
        print(f"Updates received (attempt {i+1}): {updates}")
        time.sleep(5)

    logger.info("Test completed successfully.")
    print("Test completed successfully.")

except telegram.error.Conflict as conflict_error:
    logger.error(f"Conflict Error: {conflict_error}")
    print("Conflict error occurred. Please check for duplicate bot instances.")

except telegram.error.Unauthorized as unauthorized_error:
    logger.error(f"Unauthorized Error: {unauthorized_error}")
    print("Unauthorized error occurred. Please check your BOT_TOKEN.")

except Exception as e:
    logger.error(f"General Error: {e}")
    print(f"An error occurred: {e}")

logger.info("Telegram API test finished.")

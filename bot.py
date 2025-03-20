import os
import telegram
import logging
import time

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

try:
    bot = telegram.Bot(token=BOT_TOKEN)
    print(bot.get_me())
    for i in range(3):
        updates = bot.get_updates()
        print(f"Attempt {i+1}: {updates}")
        time.sleep(5)

    print("Test completed successfully.") #added a success message.

except telegram.error.Conflict as conflict_error:
    logging.error(f"Conflict Error: {conflict_error}")
    print("Conflict error occurred. Please check for duplicate bot instances.")

except Exception as e:
    logging.error(f"Error: {e}")
    print(f"An error occurred: {e}") #added print statement for general errors.

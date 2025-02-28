import os
import time
import threading
import logging
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Get environment variables (Render supports these easily)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_TELEGRAM_ID")  # Your Telegram ID for heartbeat messages

logging.basicConfig(level=logging.INFO)

heartbeat_code = 1  # To alternate between Code 1 and 2

def send_heartbeat():
    global heartbeat_code

    bot = Bot(TOKEN)
    while True:
        try:
            bot.send_message(
                chat_id=OWNER_ID,
                text=f"✅ Bot Heartbeat - Code {heartbeat_code} - Bot is Running."
            )
            heartbeat_code = 2 if heartbeat_code == 1 else 1
            time.sleep(60)
        except Exception as e:
            logging.error(f"Heartbeat failed: {e}")
            time.sleep(30)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Hello! I'm your Telegram bot running on Render.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))

    threading.Thread(target=send_heartbeat, daemon=True).start()

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

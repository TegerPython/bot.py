import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Note: CHANNEL_ID should be a string here
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("test_question command received")
    if update.effective_user.id != OWNER_ID:
        logger.info("User not authorized")
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    try:
        logger.info(f"Attempting to send message to channel {CHANNEL_ID}")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHANNEL_ID,
            "text": "This is a test message from the bot (using requests).",
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        logger.info("Message sent successfully (using requests)")
        await update.message.reply_text("✅ Test message sent to channel (using requests).")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message (using requests): {e}")
        await update.message.reply_text(
            f"❌ Failed to send test message (using requests): {e}"
        )
    except Exception as e:
        logger.error(f"Error: unexpected error: {e}")
        await update.message.reply_text(f"❌ unexpected error, check logs")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("✅ Webhook refreshed.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("setwebhook", set_webhook))

    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()

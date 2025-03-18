import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Test command received!")
    await update.message.reply_text("Test command received!")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("Webhook refreshed.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("test", test_command))
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

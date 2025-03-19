import os
import logging
from telegram.ext import Application, MessageHandler, filters, ContextTypes, Update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APP_NAME = os.getenv("RENDER_APP_NAME")
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received update: {update}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    PORT = int(os.environ.get("PORT", "5000"))
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}",
        secret_token=TELEGRAM_SECRET_TOKEN
    )

if __name__ == "__main__":
    main()

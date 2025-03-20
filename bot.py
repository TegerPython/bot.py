import os
import logging
import asyncio
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# Weekly questions
weekly_questions = [
    {
        "question": "What is the capital of France?",
        "options": ["Paris", "London", "Berlin", "Madrid"],
        "correct_option": 0
    },
    {
        "question": "Which planet is closest to the sun?",
        "options": ["Mercury", "Venus", "Earth", "Mars"],
        "correct_option": 0
    },
    {
        "question": "What is 2+2?",
        "options": ["3", "4", "5", "6"],
        "correct_option": 1
    }
]

async def send_poll_with_delay(context, question_index):
    """Send a single poll with proper timing"""
    if question_index >= len(weekly_questions):
        # All questions sent, send completion message
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="Weekly test completed! Thank you for participating."
        )
        return
    
    question = weekly_questions[question_index]
    logger.info(f"Sending question {question_index+1}: {question['question']}")
    
    try:
        # Send poll
        await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=5,
            is_anonymous=True  # Change this to True
        )
        logger.info(f"Poll {question_index+1} sent, scheduling next poll")
        
        # Schedule next poll after this one completes
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_poll_with_delay(ctx, question_index + 1)), 
            7  # Wait 7 seconds before sending next poll
        )
    except Exception as e:
        logger.error(f"Error sending poll {question_index+1}: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    user_id = update.effective_user.id
    
    # Log who triggered the command and from where
    logger.info(f"Weekly test triggered by user {user_id} from chat {update.effective_chat.id}")
    
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    # Start the sequence with the first question
    await update.message.reply_text(f"Starting weekly test in channel {CHANNEL_ID}...")
    
    # Send first poll and let the chain continue
    await send_poll_with_delay(context, 0)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
    # Register error handler
    application.add_error_handler(lambda update, context: logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Check if webhook URL is provided
    if WEBHOOK_URL:
        # Run in webhook mode
        logger.info(f"Starting bot in webhook mode on port {PORT}")
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url
        )
    else:
        # Run in polling mode
        logger.info("Starting bot in polling mode")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

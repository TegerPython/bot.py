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

async def send_weekly_test(context: ContextTypes.DEFAULT_TYPE):
    """Send a series of polls to the channel with short timing"""
    logger.info("Starting weekly test sequence")
    
    for i, question in enumerate(weekly_questions):
        try:
            logger.info(f"Sending question {i+1}: {question['question']}")
            
            # Send poll to channel
            poll_message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=5,  # 5 seconds per question
                is_anonymous=False
            )
            
            logger.info(f"Poll {i+1} sent successfully")
            
            # Wait for poll to complete before sending next one
            await asyncio.sleep(6)  # Wait slightly longer than open_period
            
        except Exception as e:
            logger.error(f"Error sending weekly test question {i+1}: {e}")
    
    # Send completion message
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="Weekly test completed! Thank you for participating."
        )
    except Exception as e:
        logger.error(f"Error sending completion message: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    user_id = update.effective_user.id
    
    # Allow both owner and direct requests from the channel
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    await update.message.reply_text("Starting weekly test in the channel...")
    
    # Start weekly test process
    await send_weekly_test(context)

async def test_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /testpoll"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question="Test Poll?",
            options=["Yes", "No"],
            type=Poll.QUIZ,
            correct_option_id=0,
            open_period=5,
            is_anonymous=False
        )
        
        await update.message.reply_text(f"Test poll sent to channel. ID: {poll_message.poll.id}")
    except Exception as e:
        logger.error(f"Error sending test poll: {e}")
        await update.message.reply_text(f"Error: {str(e)}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("testpoll", test_poll_command))
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

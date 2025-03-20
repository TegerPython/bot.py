import os
import logging
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes

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

# Current question index
current_question_index = 0

async def send_next_question(context: ContextTypes.DEFAULT_TYPE):
    """Send the next question in the weekly test sequence"""
    global current_question_index
    
    # Check if we've sent all questions
    if current_question_index >= len(weekly_questions):
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="Weekly test completed! Thank you for participating."
        )
        current_question_index = 0  # Reset for next test
        return
    
    # Get the current question
    question = weekly_questions[current_question_index]
    logger.info(f"Sending question {current_question_index + 1}: {question['question']}")
    
    try:
        # Send poll to channel
        await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=5,  # 5 seconds per question
            is_anonymous=False
        )
        
        # Increment question index
        current_question_index += 1
        
        # Schedule the next question
        context.job_queue.run_once(send_next_question, 6)  # Wait 6 seconds before next question
        
    except Exception as e:
        logger.error(f"Error sending question: {e}")
        # Try to recover by sending the next question
        current_question_index += 1
        context.job_queue.run_once(send_next_question, 2)

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    global current_question_index
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    # Reset question index
    current_question_index = 0
    
    # Notify user
    await update.message.reply_text("Starting weekly test in the channel...")
    
    # Start the question sequence
    await send_next_question(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
    # Error handler
    def error_handler(update, context):
        logger.error(f"Error: {context.error}", exc_info=context.error)
    application.add_error_handler(error_handler)
    
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

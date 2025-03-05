import os
import json
import logging
import requests
import pytz
from datetime import datetime, timedelta
from telegram import Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
questions = []
leaderboard = {}
scheduler = BackgroundScheduler(timezone=pytz.utc)
HEARTBEAT_COUNTER = 0

def fetch_remote_data():
    global questions, leaderboard
    try:
        # Load questions
        questions_response = requests.get(os.getenv("QUESTIONS_JSON_URL"))
        questions = questions_response.json()
        
        # Load leaderboard
        leaderboard_response = requests.get(os.getenv("LEADERBOARD_JSON_URL"))
        leaderboard = leaderboard_response.json()
        
        logger.info("Data successfully fetched from GitHub")
        
    except Exception as e:
        logger.error(f"Data fetch error: {str(e)}")

async def send_question_to_channel(context: ContextTypes.DEFAULT_TYPE, question):
    """Universal question sending function"""
    try:
        message = await context.bot.send_poll(
            chat_id=os.getenv("CHANNEL_ID"),
            question=question["question"],
            options=question["options"],
            is_anonymous=False,
            allows_multiple_answers=False
        )
        
        # Store poll data with expiration
        context.chat_data[message.poll.id] = {
            "correct_option": question["correct_option"],
            "answered_users": set(),
            "expires_at": datetime.now() + timedelta(minutes=15)
        }
        return True
        
    except Exception as e:
        logger.error(f"Failed to send question: {str(e)}")
        return False

# -------------- NEW FEATURES IMPLEMENTATION --------------
async def dual_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """Send two simultaneous heartbeat messages"""
    global HEARTBEAT_COUNTER
    owner_id = os.getenv("OWNER_TELEGRAM_ID")
    
    # First heartbeat
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"❤️ Heartbeat #{HEARTBEAT_COUNTER} - System Operational"
    )
    
    # Second heartbeat with stats
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"📊 Status Update:\nQuestions: {len(questions)}\nPlayers: {len(leaderboard)}"
    )
    
    HEARTBEAT_COUNTER += 1

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced /test command with question validation"""
    # Verify owner
    if str(update.effective_user.id) != os.getenv("OWNER_TELEGRAM_ID"):
        await update.message.reply_text("⛔️ Unauthorized")
        return

    try:
        # Fetch fresh questions for testing
        test_response = requests.get(os.getenv("QUESTIONS_JSON_URL"))
        test_questions = test_response.json()
        
        if not test_questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        # Send first question to channel
        success = await send_question_to_channel(context, test_questions[0])
        
        # Send confirmation
        await update.message.reply_text(
            "✅ Test question sent to channel!" if success 
            else "❌ Failed to send test question"
        )
        
    except Exception as e:
        logger.error(f"Test command error: {str(e)}")
        await update.message.reply_text("🔥 Critical test failure!")

# -------------- SCHEDULER SETUP --------------
def setup_scheduled_jobs(application):
    # Daily questions
    for time in ["08:00", "12:00", "18:00"]:
        hour, minute = map(int, time.split(":"))
        scheduler.add_job(
            send_question_to_channel,
            trigger=CronTrigger(hour=hour, minute=minute),
            args=[application, questions.pop(0)] if questions else [application, {}]
        )
    
    # Daily leaderboard summary
    scheduler.add_job(
        post_daily_leaderboard,
        trigger=CronTrigger(hour=0, minute=5)  # 00:05 daily
    )
    
    # Dual heartbeat system
    scheduler.add_job(
        dual_heartbeat,
        'interval',
        minutes=1,
        args=[application]
    )

# -------------- MAIN APPLICATION --------------
def main():
    # Initial setup
    fetch_remote_data()
    
    # Create bot application
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Register handlers
    application.add_handlers([
        CommandHandler("test", test_command),
        CommandHandler("leaderboard", show_leaderboard),
        PollAnswerHandler(handle_poll_answer)
    ])
    
    # Start scheduler
    setup_scheduled_jobs(application)
    scheduler.start()
    
    # Webhook configuration
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL"),
        url_path="/webhook"
    )

if __name__ == "__main__":
    main()

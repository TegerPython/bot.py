import os
import json
import logging
import requests
import pytz
import asyncio
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
    """Fetch questions and leaderboard from GitHub"""
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

async def send_question_to_channel(context: ContextTypes.DEFAULT_TYPE):
    """Send a question to the channel"""
    global questions
    if not questions:
        fetch_remote_data()
        if not questions:
            logger.error("No questions available")
            return False
    
    question = questions.pop(0)
    try:
        message = await context.bot.send_poll(
            chat_id=os.getenv("CHANNEL_ID"),
            question=question["question"],
            options=question["options"],
            is_anonymous=True,  # CHANGED TO TRUE FOR CHANNEL COMPATIBILITY
            allows_multiple_answers=False
        )
        
        context.chat_data[message.poll.id] = {
            "correct_option": question["correct_option"],
            "answered_users": set(),
            "expires_at": datetime.now() + timedelta(minutes=15)
        }
        
        # Update GitHub questions
        requests.put(os.getenv("QUESTIONS_JSON_URL"), json=questions)
        return True
        
    except Exception as e:
        logger.error(f"Failed to send question: {str(e)}")
        return False

async def dual_heartbeat():
    """Send two simultaneous heartbeat messages"""
    global HEARTBEAT_COUNTER
    owner_id = os.getenv("OWNER_TELEGRAM_ID")
    
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    await app.initialize()
    
    await app.bot.send_message(
        chat_id=owner_id,
        text=f"❤️ Heartbeat #{HEARTBEAT_COUNTER} - System Operational"
    )
    
    await app.bot.send_message(
        chat_id=owner_id,
        text=f"📊 Status Update:\nQuestions: {len(questions)}\nPlayers: {len(leaderboard)}"
    )
    
    HEARTBEAT_COUNTER += 1
    await app.shutdown()

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /test command"""
    if str(update.effective_user.id) != os.getenv("OWNER_TELEGRAM_ID"):
        await update.message.reply_text("⛔️ Unauthorized")
        return

    try:
        success = await send_question_to_channel(context)
        await update.message.reply_text(
            "✅ Test question sent to channel!" if success 
            else "❌ Failed to send test question"
        )
    except Exception as e:
        logger.error(f"Test command error: {str(e)}")
        await update.message.reply_text("🔥 Critical test failure!")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leaderboard command"""
    try:
        sorted_entries = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
        response = ["🏆 Leaderboard 🏆"]
        
        for idx, (user_id, data) in enumerate(sorted_entries[:25], 1):
            response.append(f"{idx}. {data['name']}: {data['score']} points")
            
        await update.message.reply_text("\n".join(response))
    except Exception as e:
        logger.error(f"Leaderboard error: {str(e)}")
        await update.message.reply_text("⚠️ Couldn't load leaderboard")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers"""
    answer = update.poll_answer
    poll_data = context.chat_data.get(answer.poll_id, {})
    
    if not poll_data or answer.user.id in poll_data["answered_users"]:
        return
    
    if answer.option_ids[0] == poll_data["correct_option"]:
        user_id = str(answer.user.id)
        leaderboard[user_id] = {
            "score": leaderboard.get(user_id, {"score": 0})["score"] + 1,
            "name": answer.user.first_name
        }
        poll_data["answered_users"].add(answer.user.id)
        
        # Update GitHub leaderboard
        requests.put(os.getenv("LEADERBOARD_JSON_URL"), json=leaderboard)
        await context.bot.send_message(
            chat_id=os.getenv("CHANNEL_ID"),
            text=f"🎉 {answer.user.first_name} got it right! +1 point!"
        )

def scheduler_wrapper(func):
    """Wrapper for async scheduler jobs"""
    def wrapper():
        asyncio.run(func())
    return wrapper

def setup_scheduled_jobs():
    """Configure all scheduled jobs"""
    # Heartbeat every minute
    scheduler.add_job(
        scheduler_wrapper(dual_heartbeat),
        'interval',
        minutes=1
    )
    
    # Daily questions
    for time in ["08:00", "12:00", "18:00"]:
        hour, minute = map(int, time.split(":"))
        scheduler.add_job(
            send_question_to_channel,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=pytz.utc),
            args=[Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build().bot]
        )

def main():
    """Main application entry point"""
    fetch_remote_data()
    
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Register handlers
    application.add_handlers([
        CommandHandler("test", test_command),
        CommandHandler("leaderboard", show_leaderboard),
        PollAnswerHandler(handle_poll_answer)
    ])
    
    # Setup and start scheduler
    setup_scheduled_jobs()
    scheduler.start()
    
    # Run webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL"),
        url_path="/webhook"
    )

if __name__ == "__main__":
    main()

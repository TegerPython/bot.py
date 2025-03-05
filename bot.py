import os
import json
import logging
import requests
import pytz
from datetime import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    PollAnswerHandler,
    MessageHandler,
    filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

questions = []
leaderboard = {}
scheduler = BackgroundScheduler(timezone=pytz.utc)

def fetch_data():
    global questions, leaderboard
    try:
        # Fetch questions
        questions_response = requests.get(os.getenv("QUESTIONS_JSON_URL"))
        questions_response.raise_for_status()
        questions = questions_response.json()
        logger.info(f"Loaded {len(questions)} questions")

        # Fetch leaderboard
        leaderboard_response = requests.get(os.getenv("LEADERBOARD_JSON_URL"))
        leaderboard_response.raise_for_status()
        leaderboard = leaderboard_response.json()
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")

    except Exception as e:
        logger.error(f"Data fetch error: {str(e)}")
        questions = []
        leaderboard = {}

def update_github_file(filename: str, content: dict):
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{filename}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # Get current SHA
        current_file = requests.get(url, headers=headers).json()
        sha = current_file.get("sha", "")
        
        # Prepare update
        data = {
            "message": f"Update {filename}",
            "content": json.dumps(content, indent=2).encode("utf-8").decode("utf-8"),
            "sha": sha
        }
        
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info(f"Successfully updated {filename}")
        else:
            logger.error(f"Failed to update {filename}: {response.text}")
            
    except Exception as e:
        logger.error(f"GitHub update error: {str(e)}")

async def send_scheduled_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        fetch_data()
    
    if questions:
        question = questions.pop(0)
        
        if question['type'] == 'poll':
            message = await context.bot.send_poll(
                chat_id=os.getenv("CHANNEL_ID"),
                question=question['question'],
                options=question['options'],
                is_anonymous=False,
                allows_multiple_answers=False
            )
            # Store poll data with expiration time (15 minutes)
            context.chat_data[message.poll.id] = {
                "correct_option": question['correct_option'],
                "answered_users": set(),
                "expires_at": datetime.now() + timedelta(minutes=15)
            }

        update_github_file("questions.json", questions)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_data = context.chat_data.get(answer.poll_id, {})
    
    if not poll_data or answer.user.id in poll_data["answered_users"]:
        return
    
    if answer.option_ids[0] == poll_data["correct_option"]:
        user_id = str(answer.user.id)
        leaderboard[user_id] = leaderboard.get(user_id, 0) + 1
        poll_data["answered_users"].add(answer.user.id)
        
        # Announce first correct answer
        await context.bot.send_message(
            chat_id=os.getenv("CHANNEL_ID"),
            text=f"🎉 {answer.user.first_name} got it right first! +1 point!"
        )
        
        update_github_file("leaderboard.json", leaderboard)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Bot is operational!\n"
             f"📚 Questions loaded: {len(questions)}\n"
             f"🏆 Leaderboard entries: {len(leaderboard)}"
    )

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "\n".join([f"{i+1}. {uid}: {score}" for i, (uid, score) in enumerate(sorted_board[:10])])
    await update.message.reply_text(f"🏆 Top 10 Leaderboard:\n{text}")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=os.getenv("CHANNEL_ID"),
        text="❤️ Bot heartbeat - system operational"
    )

def setup_scheduler(application):
    # Daily question schedule
    question_times = [
        CronTrigger(hour=8, minute=0, timezone=pytz.utc),
        CronTrigger(hour=12, minute=0, timezone=pytz.utc),
        CronTrigger(hour=18, minute=0, timezone=pytz.utc)
    ]
    
    for trigger in question_times:
        scheduler.add_job(
            send_scheduled_question,
            trigger=trigger,
            args=[application]
        )
    
    # Hourly heartbeat
    scheduler.add_job(
        heartbeat,
        'interval',
        hours=1,
        args=[application]
    )

def main():
    # Initial data load
    fetch_data()
    
    # Create application
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Register handlers
    application.add_handlers([
        CommandHandler("start", lambda u,c: u.message.reply_text("Welcome to Daily English Quiz!")),
        CommandHandler("test", test_command),
        CommandHandler("leaderboard", show_leaderboard),
        PollAnswerHandler(handle_poll_answer)
    ])
    
    # Setup scheduler
    setup_scheduler(application)
    scheduler.start()
    
    # Webhook configuration
    port = int(os.getenv("PORT", 8443))
    webhook_url = os.getenv("WEBHOOK_URL")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="/webhook",
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()

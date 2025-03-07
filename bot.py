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

def update_github_file(filename: str, content: dict):
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{filename}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        current_file = requests.get(url, headers=headers).json()
        data = {
            "message": f"Update {filename}",
            "content": json.dumps(content, indent=2).encode("utf-8").decode("utf-8"),
            "sha": current_file.get("sha", "")
        }
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info(f"Updated {filename} successfully")
    except Exception as e:
        logger.error(f"GitHub update failed: {str(e)}")

async def send_question_to_channel(context: ContextTypes.DEFAULT_TYPE, question):
    try:
        message = await context.bot.send_poll(
            chat_id=os.getenv("CHANNEL_ID"),
            question=question["question"],
            options=question["options"],
            is_anonymous=False,
            allows_multiple_answers=False
        )
        
        context.chat_data[message.poll.id] = {
            "correct_option": question["correct_option"],
            "answered_users": set(),
            "expires_at": datetime.now() + timedelta(minutes=15)
        }
        return True
    except Exception as e:
        logger.error(f"Failed to send question: {str(e)}")
        return False

async def dual_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    global HEARTBEAT_COUNTER
    owner_id = os.getenv("OWNER_TELEGRAM_ID")
    
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"❤️ Heartbeat #{HEARTBEAT_COUNTER} - System Operational"
    )
    
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"📊 Status Update:\nQuestions: {len(questions)}\nPlayers: {len(leaderboard)}"
    )
    
    HEARTBEAT_COUNTER += 1

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv("OWNER_TELEGRAM_ID"):
        await update.message.reply_text("⛔️ Unauthorized")
        return

    try:
        test_response = requests.get(os.getenv("QUESTIONS_JSON_URL"))
        test_questions = test_response.json()
        
        if not test_questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        success = await send_question_to_channel(context, test_questions[0])
        
        await update.message.reply_text(
            "✅ Test question sent to channel!" if success 
            else "❌ Failed to send test question"
        )
    except Exception as e:
        logger.error(f"Test command error: {str(e)}")
        await update.message.reply_text("🔥 Critical test failure!")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sorted_entries = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
        response = ["🏆 Leaderboard 🏆"]
        
        for idx, (user_id, score) in enumerate(sorted_entries[:25], 1):
            user = await context.bot.get_chat(user_id)
            response.append(f"{idx}. {user.first_name}: {score} points")
            
        await update.message.reply_text("\n".join(response))
    except Exception as e:
        logger.error(f"Leaderboard error: {str(e)}")
        await update.message.reply_text("⚠️ Couldn't load leaderboard")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_data = context.chat_data.get(answer.poll_id, {})
    
    if not poll_data or answer.user.id in poll_data["answered_users"]:
        return
    
    if answer.option_ids[0] == poll_data["correct_option"]:
        user_id = str(answer.user.id)
        leaderboard[user_id] = leaderboard.get(user_id, 0) + 1
        poll_data["answered_users"].add(answer.user.id)
        
        update_github_file("leaderboard.json", leaderboard)
        await context.bot.send_message(
            chat_id=os.getenv("CHANNEL_ID"),
            text=f"🎉 {answer.user.first_name} got it right! +1 point!"
        )

async def post_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    sorted_entries = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    top_5 = "\n".join([f"{idx}. {uid}: {score}" for idx, (uid, score) in enumerate(sorted_entries[:5], 1)])
    
    await context.bot.send_message(
        chat_id=os.getenv("CHANNEL_ID"),
        text=f"📊 Daily Leaderboard:\n{top_5}"
    )

def setup_scheduled_jobs(application):
    for time in ["08:00", "12:00", "18:00"]:
        hour, minute = map(int, time.split(":"))
        scheduler.add_job(
            send_question_to_channel,
            trigger=CronTrigger(hour=hour, minute=minute),
            args=[application, questions.pop(0)] if questions else [application, {}]
        )
    
    scheduler.add_job(
        post_daily_leaderboard,
        trigger=CronTrigger(hour=0, minute=5)
    )
    
    scheduler.add_job(
        dual_heartbeat,
        'interval',
        minutes=1,
        args=[application]
    )

def main():
    fetch_remote_data()
    
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    application.add_handlers([
        CommandHandler("test", test_command),
        CommandHandler("leaderboard", show_leaderboard),
        PollAnswerHandler(handle_poll_answer)
    ])
    
    setup_scheduled_jobs(application)
    scheduler.start()
    
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL"),
        url_path="/webhook"
    )

if __name__ == "__main__":
    main()

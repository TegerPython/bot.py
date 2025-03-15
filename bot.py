import os
import json
import datetime
import logging
import asyncio
import base64
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
import httpx

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")

# State management
quiz_state = {
    "questions": [],
    "leaderboard": {},
    "active_poll": None,
    "responded_users": set(),
    "polls": {}
}

async def github_api_client(method: str, path: str, data=None):
    """Universal GitHub API client"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        if method == "GET":
            return (await client.get(url, headers=headers)).json()
        elif method == "PUT":
            # Get existing SHA
            existing = await client.get(url, headers=headers)
            sha = existing.json().get("sha") if existing.status_code == 200 else None
            
            # Prepare content
            content = base64.b64encode(json.dumps(data).encode()).decode()
            payload = {
                "message": "Bot auto-update",
                "content": content,
                "sha": sha
            }
            return await client.put(url, json=payload, headers=headers)

async def data_manager():
    """Data loading with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            quiz_state["questions"] = await github_api_client("GET", "questions.json")
            quiz_state["leaderboard"] = await github_api_client("GET", "leaderboard.json")
            logger.info(f"Loaded {len(quiz_state['questions']} questions")
            return
        except Exception as e:
            logger.error(f"Data load attempt {attempt+1} failed: {e}")
            if attempt == max_retries - 1:
                quiz_state["questions"] = []
                quiz_state["leaderboard"] = {}
                raise

async def post_question(context: ContextTypes.DEFAULT_TYPE):
    """Safe question posting with state lock"""
    if not quiz_state["questions"]:
        logger.warning("No questions available")
        return

    try:
        question = quiz_state["questions"].pop(0)
        poll = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option_id"],
            explanation=question.get("explanation", "")
        )
        
        # Atomic state update
        quiz_state.update({
            "active_poll": poll.poll.id,
            "responded_users": set(),
            "polls": {**quiz_state["polls"], poll.poll.id: poll.poll}
        })
        
        await github_api_client("PUT", "questions.json", quiz_state["questions"])
        
    except Exception as e:
        logger.error(f"Question post failed: {e}")
        quiz_state["questions"].insert(0, question)  # Re-queue failed question

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer processing with validation"""
    answer = update.poll_answer
    user = update.effective_user
    
    if not (answer.poll_id == quiz_state["active_poll"] and
            user.id not in quiz_state["responded_users"]):
        return
    
    quiz_state["responded_users"].add(user.id)
    
    poll = quiz_state["polls"].get(answer.poll_id)
    if poll and answer.option_ids[0] == poll.correct_option_id:
        username = user.username or user.first_name
        quiz_state["leaderboard"][username] = quiz_state["leaderboard"].get(username, 0) + 1
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🏅 {username} got it right!"
        )
        await github_api_client("PUT", "leaderboard.json", quiz_state["leaderboard"])

async def show_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Leaderboard formatting"""
    sorted_scores = sorted(quiz_state["leaderboard"].items(), 
                         key=lambda x: x[1], reverse=True)[:10]
    board = "📊 Top Scores:\n" + "\n".join(
        f"{idx}. {name}: {points}" for idx, (name, points) in enumerate(sorted_scores, 1)
    )
    await context.bot.send_message(chat_id=CHANNEL_ID, text=board)

def schedule_tasks(app):
    """Simplified scheduling without timezone conflicts"""
    schedule = [
        (post_question, 8),
        (post_question, 12),
        (post_question, 18),
        (show_leaderboard, 19)
    ]
    
    for job, hour in schedule:
        app.job_queue.run_daily(
            job,
            time=datetime.time(hour, 0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )

async def start_bot():
    """Main bot initialization"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    app.add_handler(CommandHandler("status", lambda u,c: u.message.reply_text("✅ Operational")))
    app.add_handler(PollAnswerHandler(handle_answer))
    
    # Initial setup
    await data_manager()
    schedule_tasks(app)
    
    # Webhook config
    await app.bot.set_webhook(
        url=os.getenv("WEBHOOK_URL"),
        allowed_updates=Update.ALL_TYPES
    )
    
    # Start server
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        url_path="webhook"
    )

if __name__ == "__main__":
    # Simplified event loop management
    try:
        asyncio.get_event_loop().run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

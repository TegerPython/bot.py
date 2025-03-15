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

async def manage_github_data(action: str, file_path: str = None, data: dict = None):
    """Universal GitHub data handler using REST API"""
    async with httpx.AsyncClient() as client:
        if action == "fetch":
            url = QUESTIONS_JSON_URL if file_path == "questions" else LEADERBOARD_JSON_URL
            response = await client.get(
                url,
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            )
            return response.json()
        
        elif action == "update":
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
            
            # Get existing SHA
            existing = await client.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
            sha = existing.json().get("sha") if existing.status_code == 200 else None
            
            # Prepare update
            content = base64.b64encode(json.dumps(data).encode()).decode()
            payload = {
                "message": "Auto-update from bot",
                "content": content,
                "sha": sha
            }
            
            await client.put(
                url,
                json=payload,
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            )

async def initialize_bot_data():
    """Alternative data loading approach with fallback"""
    try:
        quiz_state["questions"] = await manage_github_data("fetch", "questions")
        quiz_state["leaderboard"] = await manage_github_data("fetch", "leaderboard")
        logger.info("Data initialized successfully")
    except Exception as e:
        logger.error(f"Data initialization failed: {e}")
        quiz_state["questions"] = []
        quiz_state["leaderboard"] = {}

async def post_question(context: ContextTypes.DEFAULT_TYPE):
    """New question posting logic with state validation"""
    if not quiz_state["questions"]:
        logger.warning("Question queue empty")
        return
    
    question = quiz_state["questions"].pop(0)
    try:
        poll = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option_id"],
            explanation=question.get("explanation", "")
        )
        
        # Update state
        quiz_state.update({
            "active_poll": poll.poll.id,
            "responded_users": set(),
            "polls": {**quiz_state["polls"], poll.poll.id: poll.poll}
        })
        
        await manage_github_data("update", "questions.json", quiz_state["questions"])
        
    except Exception as e:
        logger.error(f"Question posting failed: {e}")

async def handle_poll_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simplified answer handling with state checks"""
    response = update.poll_answer
    user = update.effective_user
    
    # Validate response
    if (response.poll_id != quiz_state["active_poll"] or 
        user.id in quiz_state["responded_users"]):
        return
    
    quiz_state["responded_users"].add(user.id)
    
    # Verify answer
    poll = quiz_state["polls"].get(response.poll_id)
    if poll and response.option_ids[0] == poll.correct_option_id:
        username = user.username or user.first_name
        quiz_state["leaderboard"][username] = quiz_state["leaderboard"].get(username, 0) + 1
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🌟 {username} got it right first!"
        )
        await manage_github_data("update", "leaderboard.json", quiz_state["leaderboard"])

async def publish_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Leaderboard formatting and posting"""
    sorted_scores = sorted(quiz_state["leaderboard"].items(), 
                         key=lambda x: x[1], reverse=True)
    board = "🏆 Leaderboard:\n" + "\n".join(
        f"{i}. {name}: {points}" for i, (name, points) in enumerate(sorted_scores, 1)
    )
    await context.bot.send_message(chat_id=CHANNEL_ID, text=board)

def schedule_tasks(app):
    """Reimagined scheduling without timezone arguments"""
    schedule = [
        (post_question, [8, 12, 18]),
        (publish_leaderboard, [19])
    ]
    
    for job, hours in schedule:
        for hour in hours:
            app.job_queue.run_daily(
                job,
                time=datetime.time(hour, 0, tzinfo=datetime.timezone.utc),
                days=tuple(range(7))
            )

async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """New health monitoring command"""
    await update.message.reply_text(f"🟢 Operational\nQuestions queued: {len(quiz_state['questions'])}")

async def run_server():
    """Revamped server initialization"""
    bot = Application.builder().token(BOT_TOKEN).build()
    
    # Configure handlers
    bot.add_handler(CommandHandler("health", health_check))
    bot.add_handler(PollAnswerHandler(handle_poll_response))
    
    # Initialize components
    await initialize_bot_data()
    schedule_tasks(bot)
    
    # Webhook configuration
    await bot.bot.set_webhook(
        url=os.getenv("WEBHOOK_URL"),
        allowed_updates=Update.ALL_TYPES
    )
    
    # Server setup
    await bot.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        url_path="webhook"
    )

if __name__ == "__main__":
    asyncio.run(run_server())

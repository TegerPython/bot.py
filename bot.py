import os
import logging
import random
import json
import requests
import time
import asyncio
import pytz
import base64
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler, filters

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "5000"))
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# Constants
QUESTION_DURATION = 30  # Default duration (seconds)
NEXT_QUESTION_DELAY = 2  # seconds between questions
MAX_QUESTIONS = 10  # Maximum number of questions per test

# Global variables for daily questions
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
answered_users = set()

# Global variables for weekly test
weekly_test_data = {
    'questions': [],
    'current_question_index': 0,
    'participants': {},
    'active': False,
    'poll_ids': {},
    'poll_messages': {},
    'channel_message_ids': [],
    'group_link': None
}

# Load Questions
def load_questions():
    global questions
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading questions: {e}")

# Load Leaderboard
def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching leaderboard from {LEADERBOARD_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding leaderboard from {LEADERBOARD_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading leaderboard: {e}")

# Load Weekly Questions from URL
def load_weekly_questions():
    global weekly_questions
    try:
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        response.raise_for_status()
        weekly_questions = response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions from {WEEKLY_QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly questions from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {WEEKLY_QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading weekly questions: {e}")

load_questions()
load_leaderboard()
load_weekly_questions()

# Daily Questions Functions
async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users, current_message_id
    answered_users = set()
    current_question = random.choice(questions)
    keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in current_question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=current_question.get("question"),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )
        if message and message.message_id:
            current_message_id = message.message_id
    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global answered_users, current_question, current_message_id, leaderboard

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = current_question.get("correct_option", "").strip()

    correct = user_answer == correct_answer

    if correct:
        await query.answer("✅ Correct!")
        if str(user_id) not in leaderboard:
            leaderboard[str(user_id)] = {"username": username, "score": 0}
        leaderboard[str(user_id)]["score"] += 1

        explanation = current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "📝 Daily Challenge (Answered)\n\n"
            f"Question: {current_question.get('question')}\n"
            f"✅ Correct Answer: {current_question.get('correct_option')}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text=edited_text
            )
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.")
    save_leaderboard()

# Weekly Test Functions
async def fetch_weekly_questions():
    """Fetch questions from external JSON URL"""
    try:
        if not WEEKLY_QUESTIONS_JSON_URL:
            logger.error("WEEKLY_QUESTIONS_JSON_URL not set")
            return []
            
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    text_content = await response.text()
                    try:
                        data = json.loads(text_content)
                        logger.info(f"Fetched {len(data)} questions")
                        return data[:MAX_QUESTIONS]
                    except json.JSONDecodeError as je:
                        logger.error(f"JSON error: {je}, content: {text_content[:200]}...")
                        return []
                logger.error(f"Failed to fetch: HTTP {response.status}")
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
    return []

async def start_weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start test immediately (owner only)"""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
        
    try:
        questions = await fetch_weekly_questions()
        if not questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        # Reset weekly test
        weekly_test_data.update({
            'questions': questions,
            'current_question_index': 0,
            'participants': {},
            'active': True,
            'poll_ids': {},
            'poll_messages': {},
            'channel_message_ids': []
        })
        
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test_data['group_link'] = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Send initial message to channel
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *Weekly Test Starting Now!*\n"
                 "Join the Discussion group to participate!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=weekly_test_data['group_link'])]
            ])
        )
        weekly_test_data['channel_message_ids'].append(channel_message.message_id)
        
        await update.message.reply_text("🚀 Starting weekly test...")
        await send_weekly_test_question(context, 0)
        
    except Exception as e:
        logger.error(f"Error starting test: {e}")
        await update.message.reply_text(f"❌ Failed to start: {str(e)}")

async def send_weekly_test_question(context, question_index):
    """Send weekly test question to group and announcement to channel"""
    if not weekly_test_data['active'] or question_index >= len(weekly_test_data['questions']):
        if weekly_test_data['active']:
            await send_weekly_test_results(context)
        return

    question = weekly_test_data['questions'][question_index]
    weekly_test_data['current_question_index'] = question_index
    
    try:
        # Send poll to group
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            protect_content=True,
            allows_multiple_answers=False,
            open_period=QUESTION_DURATION
        )
        
        # Store poll info
        weekly_test_data['poll_ids'][question_index] = group_message.poll.id
        weekly_test_data['poll_messages'][question_index] = group_message.message_id
        
        # Send channel announcement
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎯 *QUESTION {question_index + 1} IS LIVE!* 🎯\n\n"
                 f"⏱️ *Hurry!* Only {QUESTION_DURATION} seconds to answer!\n"
                 f"💡 Test your knowledge and earn points!\n\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("𝗘𝗡╸📝 Join Discussion", url=weekly_test_data['group_link'])]
            ])
        )
        weekly_test_data['channel_message_ids'].append(channel_message.message_id)
        
        # Schedule next question or results
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_weekly_test_question(ctx, question_index + 1)),
            QUESTION_DURATION + NEXT_QUESTION_DELAY, 
            name="next_weekly_question"
        )
        
        # Schedule poll closure and answer reveal
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_weekly_test_poll(ctx, question_index)),
            QUESTION_DURATION, 
            name=f"stop_weekly_poll_{question_index}"
        )
        
    except Exception as e:
        logger.error(f"Error sending weekly test question {question_index + 1}: {e}")

async def handle_weekly_test_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    
    try:
        question_index = next(
            (idx for idx, p_id in weekly_test_data['poll_ids'].items() if p_id == poll_id),
            None
        )
        if question_index is None:
            return
            
        if poll_answer.option_ids and poll_answer.option_ids[0] == weekly_test_data['questions'][question_index]["correct_option"]:
            user = poll_answer.user
            user_name = user.full_name or user.username or f"User {user.id}"
            
            if user.id not in weekly_test_data['participants']:
                weekly_test_data['participants'][user.id] = {"name": user_name, "score": 0}
            weekly_test_data['participants'][user.id]["score"] += 1
            
    except Exception as e:
        logger.error(f"Error handling weekly test poll answer: {e}")

async def stop_weekly_test_poll(context, question_index):
    """Handle poll closure and reveal answer"""
    try:
        question = weekly_test_data['questions'][question_index]
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ *Correct Answer:* {question['options'][question['correct_option']]}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error handling weekly test poll closure: {e}")

async def send_weekly_test_results(context):
    """Send final leaderboard results"""
    if not weekly_test_data['active']:
        return
        
    results = sorted(
        weekly_test_data['participants'].items(),
        key=lambda x: x[1]["score"],
        reverse=True
    )
    
    # Format leaderboard message
    message = "🏆 *Weekly Test Results* 🏆\n\n"
    if results:
        for i, (user_id, data) in enumerate(results, start=1):
            if i == 1:
                message += f"🥇 *{data['name']}* - {data['score']} pts\n"
            elif i == 2:
                message += f"🥈 *{data['name']}* - {data['score']} pts\n"
            elif i == 3:
                message += f"🥉 *{data['name']}* - {data['score']} pts\n"
            else:
                message += f"{i}. {data['name']} - {data['score']} pts\n"
    else:
        message += "No participants this week."
    
    try:
        # Delete previous channel messages
        for msg_id in weekly_test_data['channel_message_ids']:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Couldn't delete channel message {msg_id}: {e}")
        
        # Send final results
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=weekly_test_data['group_link'])]
            ])
        )
        
        weekly_test_data['active'] = False
    except Exception as e:
        logger.error(f"Error sending weekly test leaderboard: {e}")

async def schedule_weekly_test(context):
    """Schedule weekly test for Friday 6 PM Gaza time"""
    try:
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)
        
        # Calculate next Friday at 6 PM
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7
            
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)
        
        # Set up countdown and test
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_weekly_test_countdown(ctx)),
            max(0, (next_friday - now).total_seconds() - 1800),
            name="weekly_test_countdown"
        )
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_weekly_test_command(ctx, None)),
            max(0, (next_friday - now).total_seconds()),
            name="weekly_test_start"
        )
        
        logger.info(f"Scheduled next weekly test for {next_friday}")
        
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

async def send_weekly_test_countdown(context):
    """Send countdown message before weekly test"""
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        invite_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🕒 *Weekly Test Countdown!*\n\n"
                 "The weekly test starts in 30 minutes!\n"
                 "Be prepared to challenge your knowledge!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=invite_link)]
            ])
        )
    except Exception as e:
        logger.error(f"Weekly test countdown error: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await send_question(context)
    await update.message.reply_text("✅ Test question sent.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("✅ Webhook refreshed.")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logger.info(f"Leaderboard data: {leaderboard}")
        sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
        leaderboard_text = "🏆 Leaderboard 🏆\n\n"
        for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
            leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
        await update.message.reply_text(leaderboard_text)
    except KeyError as e:
        logger.error(f"Error in leaderboard_command: KeyError - {e}")
        await update.message.reply_text("❌ Failed to display leaderboard due to data error.")
    except Exception as e:
        logger.error(f"Error in leaderboard_command: {e}")
        await update.message.reply_text("❌ Failed to display leaderboard.")

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers, weekly_question_index

    if not weekly_questions:
        logger.error("No weekly questions available.")
        return

    start_index = weekly_question_index * 10
    end_index = min(start_index + 10, len(weekly_questions))

    if start_index >= len(weekly_questions):
        logger.info("All weekly questions have been used. Restarting from the beginning.")
        weekly_question_index = 0
        start_index = 0
        end_index = min(10, len(weekly_questions))

    weekly_poll_message_ids = []
    weekly_user_answers = {}

    for i in range(start_index, end_index):
        try:
            question = weekly_questions[i]
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=30  # 30 seconds
            )
            weekly_poll_message_ids.append(message.message_id)
            time.sleep(30)  # Wait for 30 seconds
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

    weekly_question_index += 1  # Increment the index after sending 10 questions
    context.job_queue.run_once(close_weekly_polls, 30 * 10)  # Close after 10 polls * 30 seconds

async def close_weekly_polls(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers
    for message_id in weekly_poll_message_ids:
        try:
            await context.bot.stop_poll(chat_id=CHANNEL_ID, message_id=message_id)
        except Exception as e:
            logger.error(f"Error closing weekly poll {message_id}: {e}")

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll
    user_id = poll.voter_count
    if poll.is_closed:
        return
    if user_id not in weekly_user_answers:
        weekly_user_answers[user_id] = poll.options[poll.correct_option_id].voter_count
    else:
        weekly_user_answers[user_id] += poll.options[poll.correct_option_id].voter_count

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_questionnaire(context)

def get_utc_time(hour, minute, timezone_str):
    tz = pytz.timezone(timezone_str)
    local_time = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_time = local_time.astimezone(pytz.utc).time()
    return utc_time

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Daily question handlers
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))

    # Weekly test scheduling
    job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,  # Initial delay
        name="initial_weekly_test_schedule"
    )

    # Heartbeat
    job_queue.run_repeating(heartbeat, interval=60)

    # Handlers
    application.add_handler(CommandHandler("startweeklytest", start_weekly_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(PollAnswerHandler(handle_weekly_test_poll_answer))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("testweekly", test_weekly))

    # Webhook or polling
    port = int(os.environ.get("PORT", 5000))
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import logging
import asyncio
import json
import aiohttp
import pytz
from datetime import datetime, timedelta
from telegram import Update, Bot, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler, CallbackQueryHandler, filters

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))
WEEKLY_LEADERBOARD_JSON_URL = os.getenv("WEEKLY_LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# Constants
QUESTION_DURATION = 10  # Default duration (seconds)
NEXT_QUESTION_DELAY = 10  # seconds between questions
MAX_QUESTIONS = 3  # Maximum number of questions per test

# Leaderboard storage
leaderboard_library = {}

def get_question_duration(question_index):
    """Return duration in seconds for the given question index"""
    if question_index == 0:  # Question 1
        return 5  # 5 seconds for Question 1
    elif question_index == 2:  # Question 3
        return 15  # 15 seconds for Question 3
    else:
        return QUESTION_DURATION  # Default duration

class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.scheduled = False
        self.scheduled_time = None
        self.channel_messages_to_delete = []

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.scheduled = False
        self.scheduled_time = None
        self.channel_messages_to_delete = []

    def add_point(self, user_id, user_name):
        if user_id not in self.participants:
            self.participants[user_id] = {"name": user_name, "score": 0}
        self.participants[user_id]["score"] += 1

    def get_results(self):
        return sorted(
            self.participants.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

weekly_test = WeeklyTest()

async def delete_forwarded_channel_message(context, message_text_pattern):
    """Delete forwarded channel message from group"""
    try:
        # Get recent messages through direct API call
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    for update in data.get('result', []):
                        if (update.get('message', {}).get('chat', {}).get('id') == DISCUSSION_GROUP_ID and
                           update.get('message', {}).get('forward_from_chat', {}).get('id') == CHANNEL_ID and
                           message_text_pattern in update.get('message', {}).get('text', '')):
                            
                            await context.bot.delete_message(
                                chat_id=DISCUSSION_GROUP_ID,
                                message_id=update['message']['message_id']
                            )
                            logger.info(f"Deleted message: {update['message']['message_id']}")
                            return
        logger.warning("Target message not found")
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def fetch_questions_from_url():
    """Fetch questions from external JSON URL"""
    try:
        if not WEEKLY_QUESTIONS_JSON_URL:
            logger.error("WEEKLY_QUESTIONS_JSON_URL not set")
            return []
            
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    return data[:MAX_QUESTIONS]
                logger.error(f"Failed to fetch questions: HTTP {response.status}")
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
    return []

async def send_channel_announcement(context):
    """Send announcement to channel with join button"""
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        keyboard = [
            [InlineKeyboardButton("🏆 Join & Participate!", url=group_link)]
        ]
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *WEEKLY TEST ANNOUNCEMENT* 📢\n\n"
                 "A new weekly test starts in 5 minutes!\n"
                 "Join our discussion group to participate!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error sending announcement: {e}")

async def send_question(context, question_index):
    """Send question to group and announcement to channel"""
    global weekly_test
    
    if not weekly_test.active or question_index >= len(weekly_test.questions):
        if weekly_test.active:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                60, name="send_leaderboard"
            )
        return

    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # Restrict messaging during quiz
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": False}
        )
        
        # Send poll to group
        question_duration = get_question_duration(question_index)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            protect_content=True,
            allows_multiple_answers=False,
            open_period=question_duration
        )
        
        # Store poll info
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Get group link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Send to channel with buttons
        keyboard = [
            [InlineKeyboardButton("📢 Join Discussion", url=group_link)],
            [InlineKeyboardButton("🏆 View Leaderboard", callback_data="view_leaderboard")]
        ]
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🚨 *QUESTION {question_index + 1} IS LIVE!* 🚨\n\n"
                 f"⏱️ {question_duration} seconds to answer!\n"
                 f"Join the group to participate!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Schedule message deletion
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(
                delete_forwarded_channel_message(ctx, f"QUESTION {question_index + 1} IS LIVE")
            ),
            2, name="delete_forwarded_message"
        )
        
        # Schedule next question or leaderboard
        if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
                NEXT_QUESTION_DELAY, name="next_question"
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                question_duration + 5, name="send_leaderboard"
            )
        
        # Schedule poll closure
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            question_duration, name=f"stop_poll_{question_index}"
        )
        
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def stop_poll_and_check_answers(context, question_index):
    """Stop poll and show correct answer"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    
    try:
        await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ *CORRECT ANSWER* ✅\n\n"
                 f"Question {question_index + 1}: {question['question']}\n"
                 f"Correct: *{question['options'][question['correct_option']]}*",
            parse_mode="Markdown"
        )
        
        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID,
                permissions={"can_send_messages": True}
            )
            
    except Exception as e:
        if "Poll has already been closed" not in str(e):
            logger.error(f"Error stopping poll: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers from group members"""
    global weekly_test
    
    try:
        if not weekly_test.active:
            return
            
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        # Find which question this poll belongs to
        question_index = next(
            (idx for idx, p_id in weekly_test.poll_ids.items() if p_id == poll_id),
            None
        )
        if question_index is None:
            return
            
        # Check if answer is correct
        if poll_answer.option_ids and poll_answer.option_ids[0] == weekly_test.questions[question_index]["correct_option"]:
            user = poll_answer.user
            user_name = user.full_name or user.username or f"User {user.id}"
            weekly_test.add_point(user.id, user_name)
            
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_leaderboard_results(context):
    """Send final leaderboard results"""
    global weekly_test, leaderboard_library
    
    if not weekly_test.active:
        return
        
    results = weekly_test.get_results()
    
    # Format leaderboard message
    message = "🏆 *WEEKLY TEST RESULTS* 🏆\n\n"
    if results:
        for i, (user_id, data) in enumerate(results, start=1):
            if i == 1:
                message += f"🥇 *{data['name']}* 🥇 - {data['score']} pts\n"
            elif i == 2:
                message += f"🥈 *{data['name']}* 🥈 - {data['score']} pts\n"
            elif i == 3:
                message += f"🥉 *{data['name']}* 🥉 - {data['score']} pts\n"
            else:
                message += f"{i}. {data['name']} - {data['score']} pts\n"
    else:
        message += "No participants this week."
    
    # Update leaderboard library
    for user_id, data in results:
        if user_id not in leaderboard_library:
            leaderboard_library[user_id] = {"name": data["name"], "score": 0}
        leaderboard_library[user_id]["score"] += data["score"]
    
    # Save to external URL if configured
    if WEEKLY_LEADERBOARD_JSON_URL:
        try:
            leaderboard_data = [
                {"rank": i, "name": data["name"], "score": data["score"]}
                for i, (user_id, data) in enumerate(results, start=1)
            ]
            
            async with aiohttp.ClientSession() as session:
                headers = {'Content-Type': 'application/json'}
                if API_AUTH_TOKEN:
                    headers['Authorization'] = f'Bearer {API_AUTH_TOKEN}'
                    
                async with session.post(
                    WEEKLY_LEADERBOARD_JSON_URL,
                    json=leaderboard_data,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Leaderboard save failed: HTTP {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error saving leaderboard: {e}")
    
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": True}
        )
        
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from channel messages"""
    query = update.callback_query
    
    try:
        if query.data == "view_leaderboard":
            results = weekly_test.get_results()
            
            message = "🏆 *CURRENT LEADERBOARD* 🏆\n\n"
            if results:
                for i, (user_id, data) in enumerate(results[:10], start=1):
                    message += f"{i}. {data['name']} - {data['score']} pts\n"
            else:
                message += "No scores yet!"
            
            await query.answer()
            await query.edit_message_text(
                text=message,
                parse_mode="Markdown"
            )
        else:
            await query.answer()
    except Exception as e:
        logger.error(f"Error handling button: {e}")
        await query.answer("⚠️ An error occurred", show_alert=True)

# Command handlers remain the same as before
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the Weekly Test Bot!\n\n"
        "Tests run every Friday at 6PM Gaza time."
    )

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start test immediately (owner only)"""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
        
    try:
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True
        
        await update.message.reply_text("🚀 Starting weekly test...")
        
        # Send announcements
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nJoin the discussion group!",
            parse_mode="Markdown"
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nGet ready!",
            parse_mode="Markdown"
        )
        
        await send_question(context, 0)
        
    except Exception as e:
        logger.error(f"Error starting test: {e}")
        await update.message.reply_text(f"❌ Failed to start: {str(e)}")

async def schedule_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule test in 5 minutes (owner only)"""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
        
    try:
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.scheduled = True
        
        await update.message.reply_text("⏱ Test scheduled to start in 5 minutes")
        await send_channel_announcement(context)
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_test(ctx)),
            300, name="start_test"
        )
    except Exception as e:
        logger.error(f"Error scheduling test: {e}")
        await update.message.reply_text(f"❌ Failed to schedule: {str(e)}")

async def stop_weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop ongoing test (owner only)"""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
        
    if not weekly_test.active:
        await update.message.reply_text("No active test to stop")
        return
        
    try:
        weekly_test.active = False
        
        # Cancel scheduled jobs
        for job in context.job_queue.jobs():
            if job.name in ["next_question", "send_leaderboard"] or job.name.startswith("stop_poll_"):
                job.schedule_removal()
        
        # Restore permissions
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": True}
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="⚠️ Test stopped by admin"
        )
        
        await update.message.reply_text("✅ Test stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping test: {e}")
        await update.message.reply_text(f"❌ Failed to stop: {str(e)}")

async def start_test(context):
    """Start scheduled test"""
    global weekly_test
    
    if not weekly_test.scheduled:
        return
        
    weekly_test.active = True
    weekly_test.scheduled = False
    
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nJoin the discussion group!",
        parse_mode="Markdown"
    )
    
    await context.bot.send_message(
        chat_id=DISCUSSION_GROUP_ID,
        text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nGet ready!",
        parse_mode="Markdown"
    )
    
    await send_question(context, 0)

async def schedule_weekly_test(context):
    """Schedule weekly test for Friday 6PM Gaza time"""
    try:
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)
        
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7
            
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0)
        
        seconds_until = (next_friday - now).total_seconds()
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(auto_schedule_test(ctx)),
            seconds_until, name="auto_schedule_test"
        )
        
        logger.info(f"Scheduled next test for {next_friday}")
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

async def auto_schedule_test(context):
    """Automatically start scheduled test"""
    try:
        questions = await fetch_questions_from_url()
        if not questions:
            logger.error("No questions for auto-scheduled test")
            await schedule_weekly_test(context)
            return
            
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.scheduled = True
        
        await send_channel_announcement(context)
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_test(ctx)),
            300, name="start_test"
        )
        
        await schedule_weekly_test(context)
    except Exception as e:
        logger.error(f"Error in auto schedule: {e}")
        await schedule_weekly_test(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("weeklytest", weekly_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("scheduletest", schedule_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("stopweekly", stop_weekly_test_command, filters=filters.ChatType.PRIVATE))
    
    # Other handlers
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # Error handler
    application.add_error_handler(lambda update, context: logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Initial scheduling
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        1, name="initial_schedule"
    )
    
    # Start bot
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

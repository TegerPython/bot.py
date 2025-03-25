import os
import logging
import asyncio
import json
import aiohttp
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# Constants
QUESTION_DURATION = 30  # Default duration (seconds)
NEXT_QUESTION_DELAY = 2  # seconds between questions
MAX_QUESTIONS = 10  # Maximum number of questions per test

class WeeklyTest:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.channel_message_ids = []
        self.group_link = None

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

async def delete_channel_messages(context):
    """Delete all channel messages from this test"""
    try:
        for msg_id in weekly_test.channel_message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
            except Exception as e:
                logger.warning(f"Couldn't delete channel message {msg_id}: {e}")
        weekly_test.channel_message_ids = []
    except Exception as e:
        logger.error(f"Error deleting channel messages: {e}")

async def fetch_questions_from_url():
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
async def start_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Send initial message to channel
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *Weekly Test Starting Now!*\n"
                 "Questions will appear in the discussion group shortly...",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=weekly_test.group_link)]
            ])
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        await update.message.reply_text("🚀 Starting weekly test...")
        await send_question(context, 0)
        
    except Exception as e:
        logger.error(f"Error starting test: {e}")
        await update.message.reply_text(f"❌ Failed to start: {str(e)}")

async def send_question(context, question_index):
    """Send question to group and announcement to channel"""
    global weekly_test
    
    if not weekly_test.active or question_index >= len(weekly_test.questions):
        if weekly_test.active:
            await send_leaderboard_results(context)
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
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Prepare channel message with dynamic timing
        time_emoji = "⏱️"
        if QUESTION_DURATION <= 10:
            time_emoji = "🚨"
        elif QUESTION_DURATION <= 20:
            time_emoji = "⏳"
        
        # Send channel announcement
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎯 *QUESTION {question_index + 1} IS LIVE!* 🎯\n\n"
                 f"{time_emoji} *Hurry!* Only {QUESTION_DURATION} seconds to answer!\n"
                 f"💡 Test your knowledge and earn points!\n\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("𝗘𝗡╸📝 Join Discussion", url=weekly_test.group_link)]
            ])
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        # Schedule next question or leaderboard
        if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
                QUESTION_DURATION + NEXT_QUESTION_DELAY, 
                name="next_question"
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                QUESTION_DURATION + 5, 
                name="send_leaderboard"
            )
        
        # Schedule poll closure and answer reveal
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            QUESTION_DURATION, 
            name=f"stop_poll_{question_index}"
        )
        
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def start_quiz(context):
    """Start the weekly quiz"""
    try:
        # Fetch questions
        questions = await fetch_questions_from_url()
        if not questions:
            logger.error("No questions available for the quiz")
            return
        
        # Reset test and set questions
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True
        
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Delete previous teaser message
        await delete_channel_messages(context)
        
        # Send quiz start message
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="*WEEKLY TEST STARTING NOW*\n\n"
                 "🌟 *Get ready for an exciting knowledge challenge!*\n"
                 "📊 Points awarded for correct answers\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("𝗘𝗡╸📝 Join Discussion", url=weekly_test.group_link)]
            ])
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        # Start first question
        await send_question(context, 0)
        
    except Exception as e:
        logger.error(f"Quiz start error: {e}")

async def stop_poll_and_check_answers(context, question_index):
    """Handle poll closure and reveal answer"""
    global weekly_test
    
    try:
        question = weekly_test.questions[question_index]
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ *Correct Answer:* {question['options'][question['correct_option']]}",
            parse_mode="Markdown"
        )
        
        # Restore permissions after last question
        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID,
                permissions={"can_send_messages": True}
            )
    except Exception as e:
        logger.error(f"Error handling poll closure: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers from group members"""
    global weekly_test
    
    try:
        if not weekly_test.active:
            return
            
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        question_index = next(
            (idx for idx, p_id in weekly_test.poll_ids.items() if p_id == poll_id),
            None
        )
        if question_index is None:
            return
            
        if poll_answer.option_ids and poll_answer.option_ids[0] == weekly_test.questions[question_index]["correct_option"]:
            user = poll_answer.user
            user_name = user.full_name or user.username or f"User {user.id}"
            weekly_test.add_point(user.id, user_name)
            
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_leaderboard_results(context):
    """Send final leaderboard results"""
    global weekly_test
    
    if not weekly_test.active:
        return
        
    results = weekly_test.get_results()
    
    # Format leaderboard message
    message = "🏆 *Final Results* 🏆\n\n"
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
        await delete_channel_messages(context)
        
        # Send final results
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=weekly_test.group_link)]
            ])
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": True}
        )
        
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def create_countdown_teaser(context):
    """Create a live countdown teaser 30 minutes before the quiz"""
    try:
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        invite_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Send initial teaser
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🕒 *Quiz Countdown Begins!*\n\n"
                 "The weekly quiz starts in 30 minutes!\n"
                 "🕒 Countdown: 30:00 minutes",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=invite_link)]
            ])
        )
        weekly_test.channel_message_ids.append(message.message_id)
        
        # Create countdown job
        async def update_countdown(remaining_time):
            try:
                await context.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=message.message_id,
                    text=f"🕒 *Quiz Countdown!*\n\n"
                         f"The weekly quiz starts in {remaining_time // 60:02d}:{remaining_time % 60:02d} minutes!\n"
                         "Get ready to test your knowledge!",
                    parse_mode="Markdown",
                    reply_markup=message.reply_markup
                )
            except Exception as e:
                logger.error(f"Countdown update error: {e}")
        
        # Schedule countdown updates every minute
        for i in range(29, 0, -1):
            context.job_queue.run_once(
                lambda ctx, time=i*60: asyncio.create_task(update_countdown(time)),
                (30-i)*60,
                name=f"countdown_{i}"
            )
        
        # Final job to start quiz and delete teaser
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_quiz(ctx)),
            1800,  # 30 minutes
            name="start_quiz"
        )
        
    except Exception as e:
        logger.error(f"Countdown teaser error: {e}")

async def start_quiz(context):
    """Start the weekly quiz"""
    try:
        # Fetch questions
        questions = await fetch_questions_from_url()
        if not questions:
            logger.error("No questions available for the quiz")
            return
        
        # Reset test and set questions
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True
        
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Delete previous teaser message
        await delete_channel_messages(context)
        
        # Send quiz start message
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🚀 *Quiz Starts Now!*\n"
                 "Get ready for the weekly challenge!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=weekly_test.group_link)]
            ])
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        # Start first question
        await send_question(context, 0)
        
    except Exception as e:
        logger.error(f"Quiz start error: {e}")

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
        
        # Calculate time for teaser (30 minutes before quiz)
        teaser_time = next_friday - timedelta(minutes=30)
        
        seconds_until_teaser = max(0, (teaser_time - now).total_seconds())
        
        # Schedule teaser
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(create_countdown_teaser(ctx)),
            seconds_until_teaser,
            name="quiz_teaser"
        )
        
        logger.info(f"Scheduled next test teaser for {teaser_time}")
        logger.info(f"Scheduled next test for {next_friday}")
        
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    
    # Poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Initial scheduling
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,  # Initial delay to let the bot start
        name="initial_schedule"
    )
    
    # Start bot
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

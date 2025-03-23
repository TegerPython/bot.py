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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

# Constants - MODIFIED FOR TESTING
QUESTION_DURATION = 5  # seconds (changed from 30 to 5 for testing)
NEXT_QUESTION_DELAY = 10  # seconds (changed from 35 to 10 for testing)
MAX_QUESTIONS = 3  # New constant to limit number of questions for testing

# Test data structure
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # question_index -> poll_id
        self.poll_messages = {}  # question_index -> poll_message_id
        self.scheduled = False
        self.scheduled_time = None
        self.channel_messages_to_delete = []  # Store message IDs to delete

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
        sorted_participants = sorted(
            self.participants.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )
        return sorted_participants

# Global test instance
weekly_test = WeeklyTest()

async def fetch_questions_from_url():
    """Fetch questions from external JSON URL"""
    try:
        if not WEEKLY_QUESTIONS_JSON_URL:
            logger.error("WEEKLY_QUESTIONS_JSON_URL not set")
            return []
            
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    # Get raw text first, then parse as JSON
                    text_content = await response.text()
                    try:
                        data = json.loads(text_content)
                        logger.info(f"Fetched {len(data)} questions from external source")
                        # Limit questions to MAX_QUESTIONS for testing
                        return data[:MAX_QUESTIONS]
                    except json.JSONDecodeError as je:
                        logger.error(f"JSON parsing error: {je}, content: {text_content[:100]}...")
                        return []
                else:
                    logger.error(f"Failed to fetch questions: HTTP {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        return []

async def send_channel_announcement(context):
    """Send announcement to channel with button to join discussion group"""
    try:
        # Create inline keyboard with button to join discussion group
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        if not chat.invite_link:
            invite_link = await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
            group_link = invite_link.invite_link
        else:
            group_link = chat.invite_link
            
        keyboard = [
            [InlineKeyboardButton("🏆 Join & Participate!", url=group_link)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send announcement message to channel
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *WEEKLY TEST ANNOUNCEMENT* 📢\n\n"
                 "A new weekly test will start in 5 minutes!\n\n"
                 "📌 *Want to earn points and compete in the leaderboard?*\n"
                 "👉 Join our discussion group by clicking the button below\n"
                 "🏅 Only answers in the discussion group count toward your score!\n\n"
                 "⏰ Test begins in 5 minutes. Get ready!",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        logger.info("Channel announcement with group join button sent successfully")
        
    except Exception as e:
        logger.error(f"Error sending channel announcement: {e}")

async def delete_forwarded_channel_message(context, message_text_pattern):
    """Delete forwarded channel message from group that matches the pattern"""
    try:
        # Get the most recent messages from the group
        messages = await context.bot.get_chat_history(DISCUSSION_GROUP_ID, limit=10)
        
        for message in messages:
            # Check if message is forwarded from channel and matches pattern
            if (message.forward_from_chat and 
                message.forward_from_chat.id == CHANNEL_ID and
                message_text_pattern in message.text):
                
                # Delete the message
                await context.bot.delete_message(DISCUSSION_GROUP_ID, message.message_id)
                logger.info(f"Deleted forwarded channel message: {message.message_id}")
                break
    except Exception as e:
        logger.error(f"Error deleting forwarded channel message: {e}")

async def send_question(context, question_index):
    """Send questions to discussion group only"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        # All questions sent, schedule leaderboard post
        logger.info("All questions sent, scheduling leaderboard results")
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # Set chat permissions to restrict member messaging during quiz
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": False}
        )
        
        # Send question to discussion group (non-anonymous)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,  # Non-anonymous to track users
            protect_content=True,  # Prevent forwarding
            allows_multiple_answers=False,
            open_period=QUESTION_DURATION  # Set timer for poll to auto-close
        )
        
        # Store the poll information
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Send announcement to discussion group for the question
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"⚠️ Answer Question {question_index + 1} in the poll above. You have {QUESTION_DURATION} seconds! Answers will be tracked for the leaderboard."
        )
        
        # Notify channel that a question is live in the group
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        if not chat.invite_link:
            invite_link = await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
            group_link = invite_link.invite_link
        else:
            group_link = chat.invite_link
            
        # For channel only, don't include join button for users already in the group
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🚨 *QUESTION {question_index + 1} IS LIVE!* 🚨\n\n"
                 f"Join the discussion group to answer and earn points!\n"
                 f"⏱️ Only {QUESTION_DURATION} seconds to answer!"
        )
        
        # Schedule deletion of the forwarded channel message from the group
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(delete_forwarded_channel_message(
                ctx, f"QUESTION {question_index + 1} IS LIVE")),
            2  # Wait 2 seconds to ensure message is forwarded before deletion
        )
        
        logger.info(f"Question {question_index + 1} sent to discussion group")
        
        # Schedule next question after delay or end if we've reached MAX_QUESTIONS
        if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
                NEXT_QUESTION_DELAY
            )
        else:
            # If this was the last question, schedule leaderboard
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                QUESTION_DURATION + 5  # Wait a bit after last question closes
            )
        
        # Schedule poll closure and restoring chat permissions
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            QUESTION_DURATION
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def stop_poll_and_check_answers(context, question_index):
    """Stop the poll in discussion group and record correct answers"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    try:
        # Poll should auto-close due to open_period, but we'll stop it explicitly too
        poll = await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        # Send correct answer message to discussion group only
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
        # Restore chat permissions if this is the last question
        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID,
                permissions={"can_send_messages": True}
            )
            
        logger.info(f"Poll for question {question_index + 1} stopped")
    except Exception as e:
        logger.error(f"Error stopping poll for question {question_index + 1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers from discussion group members"""
    global weekly_test
    
    try:
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        if not weekly_test.active:
            return
        
        # Find which question this poll belongs to
        question_index = None
        for idx, p_id in weekly_test.poll_ids.items():
            if p_id == poll_id:
                question_index = idx
                break
        
        if question_index is None:
            return
        
        # Get user information
        user = poll_answer.user
        user_id = user.id
        user_name = user.full_name if hasattr(user, 'full_name') else (
            user.username if hasattr(user, 'username') else f"User {user_id}")
        
        # Check if the user answered correctly
        if len(poll_answer.option_ids) > 0:  # Ensure user selected an option
            selected_option = poll_answer.option_ids[0]
            correct_option = weekly_test.questions[question_index]["correct_option"]
            
            if selected_option == correct_option:
                weekly_test.add_point(user_id, user_name)
                logger.info(f"User {user_name} answered question {question_index + 1} correctly")
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}", exc_info=True)

async def send_leaderboard_results(context):
    """Send the leaderboard results in a visually appealing format"""
    global weekly_test
    
    if not weekly_test.active:
        return
    
    results = weekly_test.get_results()
    logger.info(f"Preparing leaderboard with {len(results)} participants")
    
    # Create the leaderboard message
    message = "🏆 *WEEKLY TEST RESULTS* 🏆\n\n"
    
    # New leaderboard format with centered emojis for top places
    if len(results) > 0:
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
    
    # Try to save leaderboard to external URL if configured
    if WEEKLY_LEADERBOARD_JSON_URL:
        try:
            leaderboard_data = [
                {"rank": i, "name": data["name"], "score": data["score"]}
                for i, (user_id, data) in enumerate(results, start=1)
            ]
            
            async with aiohttp.ClientSession() as session:
                async with session.post(WEEKLY_LEADERBOARD_JSON_URL, 
                                        json=leaderboard_data) as response:
                    if response.status == 200:
                        logger.info("Saved leaderboard to external URL")
                    else:
                        logger.error(f"Failed to save leaderboard: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error saving leaderboard to external URL: {e}")
    
    try:
        # Send results to both channel and discussion group
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        # Restore chat permissions if they weren't already
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": True}
        )
        
        logger.info("Leaderboard results sent successfully")
        
        # Reset the test after sending results
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard results: {e}")

async def schedule_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /scheduletest to schedule a test in 5 minutes"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Verify CHANNEL_ID and DISCUSSION_GROUP_ID are set
        if CHANNEL_ID == 0 or DISCUSSION_GROUP_ID == 0:
            await update.message.reply_text("❌ CHANNEL_ID or DISCUSSION_GROUP_ID not set in environment variables.")
            logger.error("Required environment variables not set")
            return
        
        # Fetch questions from external URL
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions found. Please check WEEKLY_QUESTIONS_JSON_URL.")
            return
            
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.scheduled = True
        
        # Send immediate confirmation
        await update.message.reply_text("✅ Weekly test scheduled to start in 5 minutes.")
        
        # Send channel announcement now
        await send_channel_announcement(context)
        
        # Schedule the actual test to start in 5 minutes
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_test(ctx)), 
            300  # 5 minutes = 300 seconds
        )
        
        logger.info("Test scheduled to start in 5 minutes")
    
    except Exception as e:
        logger.error(f"Error in schedule test command: {e}")
        await update.message.reply_text(f"Failed to schedule test: {str(e)}")

async def start_test(context):
    """Start the test after scheduled delay"""
    global weekly_test
    
    if not weekly_test.scheduled:
        logger.warning("Test not scheduled, ignoring start_test call")
        return
    
    try:
        weekly_test.active = True
        weekly_test.scheduled = False
        
        # Send announcement to both channel and discussion group
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nJoin the discussion group to participate!",
            parse_mode="Markdown"
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nGet ready for the first question!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_question(context, 0)
        
        logger.info("Weekly test started")
    except Exception as e:
        logger.error(f"Error starting scheduled test: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest to start immediately - only works in private chat"""
    global weekly_test
    
    # Check if command was sent in a group - if so, ignore it
    if update.effective_chat.type != "private":
        return
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Verify CHANNEL_ID and DISCUSSION_GROUP_ID are set
        if CHANNEL_ID == 0 or DISCUSSION_GROUP_ID == 0:
            await update.message.reply_text("❌ CHANNEL_ID or DISCUSSION_GROUP_ID not set in environment variables.")
            logger.error("Required environment variables not set")
            return
        
        # Fetch questions from external URL
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions found. Please check WEEKLY_QUESTIONS_JSON_URL.")
            return
            
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test immediately...")
        
        # Send announcement to channel
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nJoin the discussion group to participate!",
            parse_mode="Markdown"
        )
        
        # Send announcement to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *WEEKLY TEST STARTING NOW* 🎮\n\nGet ready for the first question!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_question(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text(f"Failed to start weekly test: {str(e)}")

async def schedule_weekly_test(context):
    """Schedule the weekly test for Friday at 6pm Gaza time"""
    try:
        # Get current date and time in Gaza time zone
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)
        
        # Calculate next Friday at 6pm
        days_until_friday = (4 - now.weekday()) % 7  # 4 = Friday (0 is Monday)
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7  # If it's Friday after 6pm, schedule for next Friday
            
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)
        
        # Calculate seconds until next Friday at 6pm
        seconds_until_friday = (next_friday - now).total_seconds()
        
        logger.info(f"Scheduling next weekly test for {next_friday.strftime('%Y-%m-%d %H:%M:%S')} Gaza time")
        
        # Schedule the test
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(auto_schedule_test(ctx)),
            seconds_until_friday
        )
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

async def auto_schedule_test(context):
    """Automatically start the scheduled weekly test"""
    try:
        # Fetch questions from external URL
        questions = await fetch_questions_from_url()
        if not questions:
            logger.error("No questions found for auto-scheduled test")
            # Reschedule for next week
            await schedule_weekly_test(context)
            return
            
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.scheduled = True
        
        # Send channel announcement
        await send_channel_announcement(context)
        
        # Schedule the actual test to start in 5 minutes
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_test(ctx)), 
            300  # 5 minutes = 300 seconds
        )
        
        logger.info("Auto-scheduled test will start in 5 minutes")
        
        # Schedule next week's test
        await schedule_weekly_test(context)
    except Exception as e:
        logger.error(f"Error in auto schedule test: {e}")
        # Retry scheduling next week
        await schedule_weekly_test(context)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    
    # Always answer callback query to remove loading state
    await query.answer()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic start command"""
    await update.message.reply_text(
        "👋 Welcome to the Weekly Test Bot! I organize weekly quizzes in our channel.\n\n"
        "Every Friday at 6PM Gaza time, a new quiz will be available."
    )

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("weeklytest", weekly_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("scheduletest", schedule_test_command, filters=filters.ChatType.PRIVATE))
    
    # Add poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # Register error handler
    application.add_error_handler(lambda update, context: 
                                 logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Schedule initial weekly test
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        1  # Schedule immediately after startup
    )
    
    # Start the bot
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

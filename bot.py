import os
import logging
import random
import json
import requests
import time
import aiohttp
import asyncio
import pytz
import base64
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler, filters

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logger.info(f"BOT_TOKEN: {BOT_TOKEN}")

CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
PORT = int(os.getenv("PORT", "5000"))

# Constants
QUESTION_DURATION = 30  # Default duration (seconds)
NEXT_QUESTION_DELAY = 2  # seconds between questions
MAX_QUESTIONS = 10  # Maximum number of questions per test

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}
answered_users = set()
used_weekly_questions = set()

# Load Questions from URL
# At the top of your script, add:
DEBUG = True  # Set to True for extra debugging

# In your load_questions function, add:
def load_questions():
    global questions
    try:
        if DEBUG:
            logger.info(f"Attempting to load questions from {QUESTIONS_JSON_URL}")
        response = requests.get(QUESTIONS_JSON_URL)
        if DEBUG:
            logger.info(f"Response status: {response.status_code}")
        response.raise_for_status()
        questions = response.json()
        if DEBUG:
            logger.info(f"Questions loaded: {len(questions)}")
            if questions:
                logger.info(f"First question sample: {json.dumps(questions[0])[:200]}...")
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}: {e}")
        if DEBUG:
            try:
                logger.error(f"Raw response: {response.text[:500]}...")
            except:
                pass
    except Exception as e:
        logger.error(f"Error loading questions: {e}")
# Load Leaderboard from URL
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
            logger.info("send_question: message sent successfully")
        else:
            logger.info("send_question: message sending failed")

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global answered_users, current_question, current_message_id, leaderboard

    query = update.callback_query
    if not query:
        logger.error("handle_answer: No query available.")
        return
    
    await query.answer()  # Always answer the callback query

    # Check if current_question exists
    if current_question is None:
        logger.error("handle_answer: No current question available.")
        await query.answer("Sorry, no active question at the moment.", show_alert=True)
        return

    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.", show_alert=True)
        return

    answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = current_question.get("correct_option", "").strip()

    logger.info(f"User answer: '{user_answer}'")
    logger.info(f"Correct answer: '{correct_answer}'")

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
                text=edited_text,
                reply_markup=None  # Remove the inline keyboard
            )
            logger.info("handle_answer: Message edited successfully.")
        except Exception as e:
            logger.error(f"handle_answer: Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.", show_alert=True)

    save_leaderboard()

def save_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"  # Replace with your GitHub username
        repo_name = "bot_data"  # Replace with your repository name
        file_path = "leaderboard.json"

        # Get the current file's SHA for updating
        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        # Update the file
        content = json.dumps(leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",  # Or your branch name
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Leaderboard saved successfully to GitHub.")
    except Exception as e:
        logger.error(f"Error saving leaderboard to GitHub: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not questions:
        await update.message.reply_text("❌ No questions loaded!")
        return
    
    # Select a random question
    question = random.choice(questions)
    
    try:
        keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in question.get("options", [])]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=question.get("question"),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )
        
        await update.message.reply_text(f"✅ Test question sent in channel. Question: {question.get('question')}")
    except Exception as e:
        logger.error(f"Question sending error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

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

# Weekly Test Functions
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
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
        
    try:
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions available")
            return
            
        weekly_test.reset()
        weekly_test.questions = [q for q in questions if q.get("id") not in used_weekly_questions]
        if not weekly_test.questions:
            await update.message.reply_text("❌ No new questions available for the weekly quiz")
            return
        weekly_test.active = True
        
        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        # Send initial message to channel
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *Weekly Test Starting Now!*\n"
                 "Join the Discussion group to participate!...",
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
            # Add weekly scores to main leaderboard
            if str(user_id) not in leaderboard:
                leaderboard[str(user_id)] = {"username": data["name"], "score": 0}
            leaderboard[str(user_id)]["score"] += data["score"]
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
        save_leaderboard()  # Save the updated leaderboard
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

        async def debug_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    # Check key environment variables
    debug_info = "🔍 Debug Information:\n\n"
    debug_info += f"BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Missing'}\n"
    debug_info += f"CHANNEL_ID: {CHANNEL_ID}\n"
    debug_info += f"OWNER_ID: {OWNER_ID}\n"
    debug_info += f"DISCUSSION_GROUP_ID: {DISCUSSION_GROUP_ID}\n"
    debug_info += f"QUESTIONS_JSON_URL: {QUESTIONS_JSON_URL}\n"
    debug_info += f"Questions loaded: {len(questions)}\n"
    debug_info += f"Current question: {'✅ Set' if current_question else '❌ None'}\n"
    
    await update.message.reply_text(debug_info)


async def force_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_question, current_message_id, answered_users
    
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not questions:
        await update.message.reply_text("❌ No questions loaded. Check JSON URL.")
        return
    
    answered_users = set()
    current_question = random.choice(questions)
    
    await update.message.reply_text(f"✅ Manually set current_question: {current_question.get('question')}")
    
# Add this to your command handlers
application.add_handler(CommandHandler("forcequestion", force_question))

# Add this to your command handlers
application.add_handler(CommandHandler("debug", debug_env))
        
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
        weekly_test.questions = [q for q in questions if q.get("id") not in used_weekly_questions]
        if not weekly_test.questions:
            logger.error("No new questions available for the weekly quiz")
            return
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
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    
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

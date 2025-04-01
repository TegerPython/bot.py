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
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
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
QUESTION_EXPIRY_TIME = 3600  # 1 hour in seconds

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
question_expiry = None
user_answers = {}
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}
answered_users = set()
used_weekly_questions = set()

# Load Questions from URL
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

async def cleanup_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, current_message_id, answered_users, question_expiry
    
    if current_question and current_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text="⌛ This question has expired",
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"cleanup_question: Failed to edit message: {e}")
    
    current_question = None
    current_message_id = None
    answered_users = set()
    question_expiry = None
    logger.info("Cleaned up expired question")

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users, current_message_id, question_expiry
    
    # Clean up any existing question
    await cleanup_question(context)
    
    if not questions:
        logger.error("No questions available to send")
        return

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
            question_expiry = time.time() + QUESTION_EXPIRY_TIME
            logger.info(f"Question sent with ID {current_message_id}, expires at {question_expiry}")
        else:
            logger.error("Failed to get message ID after sending")
            current_question = None

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")
        current_question = None
        current_message_id = None

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug("handle_answer: function called")
    global answered_users, current_question, current_message_id, leaderboard, question_expiry

    # Early validation
    if not update.callback_query:
        logger.warning("handle_answer: No callback query in update")
        return

    query = update.callback_query
    await query.answer()

    # Check if question is still valid
    if not current_question or not current_message_id:
        logger.warning("handle_answer: No active question")
        try:
            await query.answer("⚠️ This question is no longer active", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send answer feedback: {e}")
        return

    if question_expiry and time.time() > question_expiry:
        logger.warning("handle_answer: Question has expired")
        await cleanup_question(context)
        try:
            await query.answer("⌛ This question has expired", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send expiry feedback: {e}")
        return

    user_id = query.from_user.id
    username = query.from_user.first_name or query.from_user.username or f"User {user_id}"

    # Check if user already answered
    if user_id in answered_users:
        try:
            await query.answer("❌ You already answered this question.", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send duplicate answer feedback: {e}")
        return

    # Mark user as answered
    answered_users.add(user_id)
    
    try:
        user_answer = query.data.strip()
        correct_answer = current_question.get("correct_option", "").strip()

        logger.info(f"handle_answer: User {username} (ID: {user_id}) answered: '{user_answer}'")
        logger.info(f"handle_answer: Correct answer: '{correct_answer}'")

        correct = user_answer == correct_answer

        if correct:
            # Update leaderboard
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
                    reply_markup=None
                )
                logger.info("handle_answer: message edited successfully")
            except Exception as e:
                logger.error(f"handle_answer: Failed to edit message: {e}")
            
            # Save the updated leaderboard
            save_leaderboard()
            
        else:
            # Provide feedback for incorrect answers
            try:
                await query.answer("❌ Incorrect answer!", show_alert=False)
            except Exception as e:
                logger.error(f"Failed to send incorrect answer feedback: {e}")

    except Exception as e:
        logger.error(f"Error in handle_answer processing: {e}")
        try:
            await query.answer("⚠️ Error processing your answer", show_alert=False)
        except Exception as e:
            logger.error(f"Failed to send error feedback: {e}")

def save_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"
        repo_name = "bot_data"
        file_path = "leaderboard.json"

        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        content = json.dumps(leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",
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

        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link

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

async def send_question(context, question_index):
    global weekly_test, used_weekly_questions

    if not weekly_test.active or question_index >= len(weekly_test.questions):
        if weekly_test.active:
            await send_leaderboard_results(context)
        return

    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    used_weekly_questions.add(question.get("id", question_index))

    try:
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": False}
        )

        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            protect_content=True,
            allows_multiple_answers=False,
            open_period=QUESTION_DURATION
        )

        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id

        time_emoji = "⏱️"
        if QUESTION_DURATION <= 10:
            time_emoji = "🚨"
        elif QUESTION_DURATION <= 20:
            time_emoji = "⏳"

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

        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            QUESTION_DURATION,
            name=f"stop_poll_{question_index}"
        )

    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def stop_poll_and_check_answers(context, question_index):
    global weekly_test

    try:
        question = weekly_test.questions[question_index]
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ *Correct Answer:* {question['options'][question['correct_option']]}",
            parse_mode="Markdown"
        )

        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID,
                permissions={"can_send_messages": True}
            )
    except Exception as e:
        logger.error(f"Error handling poll closure: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    global weekly_test

    if not weekly_test.active:
        return

    results = weekly_test.get_results()

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
            if str(user_id) not in leaderboard:
                leaderboard[str(user_id)] = {"username": data["name"], "score": 0}
            leaderboard[str(user_id)]["score"] += data["score"]
    else:
        message += "No participants this week."

    try:
        await delete_channel_messages(context)

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
        save_leaderboard()
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def create_countdown_teaser(context):
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        invite_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link

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

        for i in range(29, 0, -1):
            context.job_queue.run_once(
                lambda ctx, time=i * 60: asyncio.create_task(update_countdown(time)),
                (30 - i) * 60,
                name=f"countdown_{i}"
            )

        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_quiz(ctx)),
            1800,
            name="start_quiz"
        )

    except Exception as e:
        logger.error(f"Countdown teaser error: {e}")

async def start_quiz(context):
    try:
        questions = await fetch_questions_from_url()
        if not questions:
            logger.error("No questions available for the quiz")
            return

        weekly_test.reset()
        weekly_test.questions = [q for q in questions if q.get("id") not in used_weekly_questions]
        if not weekly_test.questions:
            logger.error("No new questions available for the weekly quiz")
            return
        weekly_test.active = True

        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link

        await delete_channel_messages(context)

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

        await send_question(context, 0)

    except Exception as e:
        logger.error(f"Quiz start error: {e}")

async def schedule_weekly_test(context):
    try:
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)

        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7

        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)

        teaser_time = next_friday - timedelta(minutes=30)

        seconds_until_teaser = max(0, (teaser_time - now).total_seconds())

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

    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))

    application.add_handler(PollAnswerHandler(handle_poll_answer))

    # Schedule regular cleanup
    application.job_queue.run_repeating(
        cleanup_question,
        interval=3600,  # Every hour
        first=10  # Start after 10 seconds
    )

    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,
        name="initial_schedule"
    )

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

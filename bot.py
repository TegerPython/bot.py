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

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
PORT = int(os.getenv("PORT", "5000"))
QUESTION_DURATION = 30
NEXT_QUESTION_DELAY = 2
MAX_QUESTIONS = 10

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
answered_users = set()
used_weekly_questions = set()

# Utility functions
async def fetch_json(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

# Weekly Test Class and Functions
class WeeklyTest:
    def __init__(self): self.reset()
    def reset(self): self.questions, self.current_question_index, self.participants, self.active, self.poll_ids, self.poll_messages, self.channel_message_ids, self.group_link = [], 0, {}, False, {}, {}, [], None
    def add_point(self, user_id, user_name): self.participants.setdefault(user_id, {"name": user_name, "score": 0})["score"] += 1
    def get_results(self): return sorted(self.participants.items(), key=lambda x: x[1]["score"], reverse=True)

weekly_test = WeeklyTest()

async def send_weekly_question(context, index):
    global weekly_test
    if not weekly_test.active or index >= len(weekly_test.questions): return await send_leaderboard_results(context)
    question = weekly_test.questions[index]
    weekly_test.current_question_index = index
    used_weekly_questions.add(question.get("id", index))
    await context.bot.set_chat_permissions(DISCUSSION_GROUP_ID, permissions={"can_send_messages": False})
    poll = await context.bot.send_poll(DISCUSSION_GROUP_ID, f"❓ Question {index + 1}: {question['question']}", options=question["options"], is_anonymous=False, protect_content=True, allows_multiple_answers=False, open_period=QUESTION_DURATION)
    weekly_test.poll_ids[index] = poll.poll.id
    weekly_test.poll_messages[index] = poll.message_id
    time_emoji = "⏱️" if QUESTION_DURATION > 20 else "⏳" if QUESTION_DURATION > 10 else "🚨"
    message = await context.bot.send_message(CHANNEL_ID, f"🎯 *QUESTION {index + 1} IS LIVE!* 🎯\n\n{time_emoji} *Hurry!* Only {QUESTION_DURATION} seconds to answer!\n💡 Test your knowledge and earn points!\n\n", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("𝗘𝗡╸📝 Join Discussion", url=weekly_test.group_link)]]))
    weekly_test.channel_message_ids.append(message.message_id)
    if index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
        context.job_queue.run_once(lambda ctx: asyncio.create_task(send_weekly_question(ctx, index + 1)), QUESTION_DURATION + NEXT_QUESTION_DELAY, name="next_question")
    else:
        context.job_queue.run_once(lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)), QUESTION_DURATION + 5, name="send_leaderboard")
    context.job_queue.run_once(lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, index)), QUESTION_DURATION, name=f"stop_poll_{index}")

async def stop_poll_and_check_answers(context, index):
    global weekly_test
    try:
        question = weekly_test.questions[index]
        await context.bot.send_message(DISCUSSION_GROUP_ID, f"✅ *Correct Answer:* {question['options'][question['correct_option']]}", parse_mode="Markdown")
        if index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(DISCUSSION_GROUP_ID, permissions={"can_send_messages": True})
    except Exception as e:
        logger.error(f"Error handling poll closure: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global weekly_test
    try:
        if not weekly_test.active: return
        poll_answer = update.poll_answer
        index = next((idx for idx, p_id in weekly_test.poll_ids.items() if p_id == poll_answer.poll_id), None)
        if index is None: return
        if poll_answer.option_ids and poll_answer.option_ids[0] == weekly_test.questions[index]["correct_option"]:
            user = poll_answer.user
            weekly_test.add_point(user.id, user.full_name or user.username or f"User {user.id}")
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_leaderboard_results(context):
    global weekly_test
    if not weekly_test.active: return
    results = weekly_test.get_results()
    message = "🏆 *Final Results* 🏆\n\n" + ("\n".join(f"{('🥇' if i == 1 else '🥈' if i == 2 else '🥉' if i == 3 else f'{i}.')} *{data['name']}* - {data['score']} pts" if i <= 3 else f"{i}. {data['name']} - {data['score']} pts" for i, (_, data) in enumerate(results, start=1)) if results else "No participants this week.")
    try:
        await delete_channel_messages(context)
        message_obj = await context.bot.send_message(CHANNEL_ID, message, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join Discussion", url=weekly_test.group_link)]]))
        weekly_test.channel_message_ids.append(message_obj.message_id)
        await context.bot.set_chat_permissions(DISCUSSION_GROUP_ID, permissions={"can_send_messages": True})
        weekly_test.active = False
        for user_id, data in results:
            leaderboard.setdefault(str(user_id), {"username": data["name"], "score": 0})["score"] += data["score"]
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def create_countdown_teaser(context):
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        invite_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        message = await context.bot.send_message(CHANNEL_ID, "🕒 *Quiz Countdown Begins!*\n\nThe weekly quiz starts in 30 minutes!\n🕒 Countdown: 30:00 minutes", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join Discussion", url=invite_link)]]))
        weekly_test.channel_message_ids.append(message.message_id)
        async def update_countdown(remaining_time):
            try:
                await context.bot.edit_message_text(f"🕒 *Quiz Countdown!*\n\nThe weekly quiz starts in {remaining_time // 60:02d}:{remaining_time % 60:02d} minutes!\nGet ready to test your knowledge!", chat_id=CHANNEL_ID, message_id=message.message_id, parse_mode="Markdown", reply_markup=message.reply_markup)
            except Exception as e:
                logger.error(f"Countdown update error: {e}")
        for i in range(29, 0, -1):
            context.job_queue.run_once(lambda ctx, time=i*60: asyncio.create_task(update_countdown(time)), (30-i)*60, name=f"countdown_{i}")
        context.job_queue.run_once(lambda ctx: asyncio.create_task(start_quiz(ctx)), 1800, name="start_quiz")
    except Exception as e:
        logger.error(f"Countdown teaser error: {e}")

async def start_quiz(context):
    try:
        questions = await fetch_weekly_questions()
        if not questions: return logger.error("No questions available for the quiz")
        weekly_test.reset()
        weekly_test.questions = [q for q in questions if q.get("id") not in used_weekly_questions][:MAX_QUESTIONS]
        if not weekly_test.questions: return logger.error("No new questions available for the weekly quiz")
        weekly_test.active = True
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        await delete_channel_messages(context)
        message = await context.bot.send_message(CHANNEL_ID, "🚀 *Quiz Starts Now!*\nGet ready for the weekly challenge!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join Discussion", url=weekly_test.group_link)]]))
        weekly_test.channel_message_ids.append(message.message_id)
        await send_weekly_question(context, 0)
    except Exception as e:
        logger.error(f"Quiz start error: {e}")

async def schedule_weekly_test(context):
    try:
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18: days_until_friday = 7
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)
        teaser_time = next_friday - timedelta(minutes=30)
        seconds_until_teaser = max(0, (teaser_time - now).total_seconds())
        context.job_queue.run_once(lambda ctx: asyncio.create_task(create_countdown_teaser(ctx)), seconds_until_teaser, name="quiz_teaser")
        logger.info(f"Scheduled next test teaser for {teaser_time}")
        logger.info(f"Scheduled next test for {next_friday}")
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

async def delete_channel_messages(context):
    try:
        for msg_id in weekly_test.channel_message_ids:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Couldn't delete channel message {msg_id}: {e}")
        weekly_test.channel_message_ids = []
    except Exception as e:
        logger.error(f"Error deleting channel messages: {e}")

# Main execution
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    application.job_queue.run_once(lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)), 5, name="initial_schedule")
    if WEBHOOK_URL:
        application.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}", drop_pending_updates=True)
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

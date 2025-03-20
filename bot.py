import os
import asyncio
import logging
import json
import random
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Bot Token & Config
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
QUESTIONS_JSON_URL = os.environ.get("QUESTIONS_JSON_URL")

# Enable Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store User Scores
user_scores = {}

# Load Sample Questions (3 for Testing)
test_questions = [
    {"question": "What is 2 + 2?", "options": ["3", "4", "5"], "answer": "4"},
    {"question": "What is the capital of France?", "options": ["Paris", "London", "Berlin"], "answer": "Paris"},
    {"question": "Which planet is closest to the Sun?", "options": ["Earth", "Venus", "Mercury"], "answer": "Mercury"}
]

async def start(update: Update, context: CallbackContext) -> None:
    """Start command to trigger the test sequence."""
    user_scores.clear()  # Reset scores
    await update.message.reply_text("Starting test! Answer correctly to earn points. 🏆")
    await run_test(update, context)

async def run_test(update: Update, context: CallbackContext) -> None:
    """Posts 3 questions sequentially, every 5 seconds."""
    chat_id = update.message.chat_id

    for i, q in enumerate(test_questions):
        question_text = f"❓ Question {i+1}: {q['question']}\n"
        question_text += "\n".join([f"{idx+1}. {opt}" for idx, opt in enumerate(q['options'])])
        
        await context.bot.send_message(chat_id=chat_id, text=question_text)
        
        # Store correct answer for checking
        context.user_data["current_answer"] = q["answer"]
        
        # Wait for 5 seconds before the next question
        await asyncio.sleep(5)

    # Show leaderboard after all questions
    await show_leaderboard(update, context)

async def handle_response(update: Update, context: CallbackContext) -> None:
    """Checks user answer and updates scores."""
    user_id = update.message.from_user.id
    user_answer = update.message.text.strip()
    correct_answer = context.user_data.get("current_answer")

    if correct_answer and user_answer.lower() == correct_answer.lower():
        user_scores[user_id] = user_scores.get(user_id, 0) + 1
        await update.message.reply_text("✅ Correct! 🎉")
    else:
        await update.message.reply_text("❌ Wrong answer!")

async def show_leaderboard(update: Update, context: CallbackContext) -> None:
    """Displays leaderboard after all questions."""
    if not user_scores:
        await update.message.reply_text("No correct answers were recorded. 😢")
        return

    leaderboard_text = "🏆 **Leaderboard** 🏆\n\n"
    sorted_scores = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)

    for i, (user_id, score) in enumerate(sorted_scores, start=1):
        leaderboard_text += f"{i}. User {user_id} - {score} points\n"

    await update.message.reply_text(leaderboard_text)

def main():
    """Start the bot."""
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_response))
    
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

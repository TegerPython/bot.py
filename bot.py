# Add near the top with other command functions
async def stop_weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /stopweekly to stop an ongoing test"""
    global weekly_test
    
    # Only allow from owner in private chat
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    if not weekly_test.active:
        await update.message.reply_text("No active test to stop.")
        return
    
    try:
        # Set flag to stop the test
        weekly_test.active = False
        
        # Restore chat permissions
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": True}
        )
        
        # Send notifications
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="⚠️ Weekly test has been stopped by the admin."
        )
        
        await update.message.reply_text("✅ Weekly test stopped successfully.")
        
        # Cancel any pending question jobs
        for job in context.job_queue.get_jobs_by_name("next_question"):
            job.schedule_removal()
        
        logger.info("Weekly test stopped by admin command")
    except Exception as e:
        logger.error(f"Error stopping weekly test: {e}")
        await update.message.reply_text(f"Failed to stop test: {str(e)}")

# Add this to the main() function when registering command handlers
application.add_handler(CommandHandler("stopweekly", stop_weekly_test_command, filters=filters.ChatType.PRIVATE))

# Modify send_question function to use job names for cancellation
async def send_question(context, question_index):
    # [existing code...]
    
    # Schedule next question with job name
    if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
            NEXT_QUESTION_DELAY,
            name="next_question"  # Add this job name
        )

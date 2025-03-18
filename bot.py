async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"Received answer from {query.from_user.id}")

        message_id = query.message.message_id
        user_answer = query.data.split("_")[1]
        question_data = question_manager.get_answer(message_id)

        if not question_data:
            await query.edit_message_text("⚠️ This question has expired")
            return

        if user_answer == question_data["answer"]:
            response = "✅ Correct!"
        else:
            explanation = next(
                (q.get('explanation', '') 
                for q in QUESTIONS 
                if q['question'] == question_data['question']
            ), 'No explanation available'
            response = (
                f"❌ Incorrect. Correct answer: {question_data['answer']}\n"
                f"📖 Explanation: {explanation}"
            )

        await query.edit_message_text(text=f"{query.message.text}\n\n{response}", reply_markup=None)
    except Exception as e:
        logger.error(f"Error handling answer: {str(e)}")

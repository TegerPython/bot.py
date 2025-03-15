def setup_jobs(app):
    # Define your timezone (example: UTC+3)
    tz = datetime.timezone(datetime.timedelta(hours=3))
    
    # Create timezone-aware times
    question_times = [
        datetime.time(8, 0, tzinfo=tz),
        datetime.time(12, 0, tzinfo=tz),
        datetime.time(18, 0, tzinfo=tz)
    ]
    leaderboard_time = datetime.time(19, 0, tzinfo=tz)

    # Schedule questions
    for time in question_times:
        app.job_queue.run_daily(
            send_question,
            time=time,
            days=tuple(range(7))
        )
    
    # Schedule leaderboard
    app.job_queue.run_daily(
        post_leaderboard,
        time=leaderboard_time,
        days=tuple(range(7))
    )

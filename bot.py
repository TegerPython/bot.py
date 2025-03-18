import os
import logging
import requests
import json

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variable (Replace with your actual URL)
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")

def test_weekly_json_load():
    try:
        logger.info(f"Attempting to fetch weekly questions from: {WEEKLY_QUESTIONS_JSON_URL}")
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        response.raise_for_status()
        logger.info("Weekly questions fetch successful. Attempting to decode JSON.")
        weekly_questions = response.json()
        logger.info(f"Loaded weekly questions: {weekly_questions}")
        logger.info("JSON loaded successfully.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly questions from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading weekly questions: {e}")

if __name__ == "__main__":
    test_weekly_json_load()

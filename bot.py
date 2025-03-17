import os
import json
import logging
import asyncio
import pytz
from datetime import datetime, timedelta, time  # <-- Added time import
from telegram import Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes
)
import httpx
import base64
import random

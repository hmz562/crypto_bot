# core/constants.py

import os
from dotenv import load_dotenv
load_dotenv()

TOKEN1        = os.getenv("TELEGRAM_TOKEN1")
TOKEN2        = os.getenv("TELEGRAM_TOKEN2")
BOT2_CHAT_ID  = os.getenv("BOT2_CHAT_ID")
BOT1_USERNAME = os.getenv("BOT1_USERNAME")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

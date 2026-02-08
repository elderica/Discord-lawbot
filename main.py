import os
import asyncio
import httpx
import unicodedata
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from contextlib import asynccontextmanager

# --- 設定 ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BASE_URL = "https://laws.e-gov.go.jp/api/2"

LAW_MASTER = {
    "労働基準法": "322AC0000000049_20250601_504AC0000000068",
    "労働契約法": "419AC0000000128_20200401_430AC0000000071",
    "消費者契約法": "412AC0000000061_20250601_504AC0000000068"
}

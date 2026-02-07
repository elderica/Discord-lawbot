import os
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
import uvicorn
from contextlib import asynccontextmanager

# --- 設定（環境変数） ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
LAW_API_V2 = "https://elaws.e-gov.go.jp/api/2/lawdata/321CONSTITUTION"

# --- 起動時の処理 (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時にスラッシュコマンドをDiscordに登録
    async with httpx.AsyncClient() as client:
        url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "name": "law",
            "description": "日本国憲法を表示します(v2)",
            "options": [{"name": "number", "description": "条文番号（例：9）", "type": 3, "required": True}]
        }
        await client.post(url, headers=headers, json=payload)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok"}

# --- Discordからのリクエスト受け取り口 ---
@app.post("/interactions")
async def interactions(request: Request):
    # 署名検証
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    
    verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
    try:
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid request signature")

    data = await request.json()
    
    # Ping (Discordからの接続確認)
    if data.get("type") == 1:
        return {"type": 1}


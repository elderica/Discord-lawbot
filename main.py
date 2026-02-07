import os
import asyncio
import httpx
import sys
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from contextlib import asynccontextmanager
import logging

# ロギング設定を強化
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- 設定 ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BASE_URL = "https://laws.e-gov.go.jp/api/2"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 80)
    logger.info("APPLICATION STARTING")
    logger.info("=" * 80)
    
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}

        # グローバルコマンドを全削除
        await client.put(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands",
            headers=headers,
            json=[]
        )
        logger.info("Global commands cleared")

        # ギルドコマンド登録
        GUILD_ID = "1467465108690043016"
        payload = {
            "name": "law_search",
            "description": "法令を検索して条文を表示します",
            "options": [
                {
                    "name": "name",
                    "description": "法令名（例：民法、憲法）",
                    "type": 3,
                    "required": True
                },
                {
                    "name": "number",
                    "description": "条文番号（例：1）",
                    "type": 3,
                    "required": True
                }
            ]
        }

        await client.post(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands",
            headers={**headers, "Content-Type": "application/json"},
            json=payload
        )
        logger.info("Guild command registered")
    
    logger.info("Application ready")
    yield
    logger.info("Application shutting down")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok"}

async def fetch_law_data(token: str, law_name: str, target_no: str):
    logger.info("=" * 80)
    logger.info(f"FETCH_LAW_DATA STARTED: law_name='{law_name}', article={target_no}")
    logger.info("=" * 80)
    
    async with httpx.AsyncClient() as client:
        try:
            # Test 1: 直接APIを叩く
            test_url = "https://laws.e-gov.go.jp/api/2/laws?lawName=民法"
            logger.info(f"TEST 1: Calling {test_url}")
            
            test_res = await client.get(test_url, timeout=15)
            logger.info(f"TEST 1: Status={test_res.status_code}")
            logger.info(f"TEST 1: Content-Type={test_res.headers.get('content-type')}")
            logger.info(f"TEST 1: Body length={len(test_res.text)}")
            logger.info(f"TEST 1: Body preview (first 2000 chars):")
            logger.info(test_res.text[:2000])
            
            if test_res.status_code == 200:
                try:
                    test_json = test_res.json()
                    logger.info(f"TEST 1: JSON parsed OK")
                    logger.info(f"TEST 1: JSON structure:")
                    import json
                    logger.info(json.dumps(test_json, ensure_ascii=False, indent=2))
                except Exception as e:
                    logger.error(f"TEST 1: JSON parsing failed: {e}")
            
            # とりあえずメッセージ送信
            logger.info("Sending response to Discord")
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={
                    "content": f"✅ デバッグ実行完了\n検索: {law_name} 第{target_no}条\nサーバーログを確認してください"
                }
            )
            logger.info("Response sent to Discord")

        except Exception as e:
            logger.error(f"ERROR in fetch_law_data: {type(e).__name__}: {str(e)}", exc_info=True)
            try:
                await client.patch(
                    f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                    json={"content": f"⚠️ エラー: {str(e)}"}
                )
            except:
                pass

@app.post("/interactions")
async def interactions(request: Request):
    logger.info("=" * 80)
    logger.info("INTERACTION RECEIVED")
    
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    
    logger.info(f"Signature present: {signature is not None}")
    logger.info(f"Timestamp present: {timestamp is not None}")
    
    if not signature or not timestamp:
        logger.warning("Missing signature or timestamp")
        raise HTTPException(status_code=401)

    body = await request.body()
    logger.info(f"Body length: {len(body)}")
    
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            timestamp.encode() + body,
            bytes.fromhex(signature)
        )
        logger.info("Signature verified OK")
    except Exception as e:
        logger.error(f"Signature verification failed: {e}")
        raise HTTPException(status_code=401)

    data = await request.json()
    logger.info(f"Request type: {data.get('type')}")
    logger.info(f"Full data: {data}")

    # PING
    if data.get("type") == 1:
        logger.info("Responding to PING")
        return {"type": 1}

    # SLASH COMMAND
    if data.get("type") == 2:
        logger.info("Processing SLASH COMMAND")
        token = data["token"]
        options = data["data"].get("options", [])

        law_name = None
        target_no = None

        for opt in options:
            if opt["name"] == "name":
                law_name = opt["value"]
            elif opt["name"] == "number":
                target_no = str(opt["value"])

        logger.info(f"Extracted: law_name='{law_name}', target_no='{target_no}'")

        if not law_name or not target_no:
            logger.warning("Missing law_name or target_no")
            return {
                "type": 4,
                "data": {"content": "法令名と条文番号を指定してください。"}
            }

        logger.info("Creating async task for fetch_law_data")
        asyncio.create_task(fetch_law_data(token, law_name, target_no))
        logger.info("Returning deferred response (type 5)")
        return {"type": 5}

    logger.info("Unknown interaction type, returning status ok")
    return {"status": "ok"}
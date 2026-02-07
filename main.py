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
LAW_API_V2 = "https://laws.e-gov.go.jp/api/2/lawdata/321CONSTITUTION.json"

@asynccontextmanager
async def lifespan(app: FastAPI):
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

# --- v2 JSON解析 & メッセージ更新ロジック ---
async def fetch_v2_and_edit_response(token, target_no):
    async with httpx.AsyncClient() as client:
        try:
            # e-Gov APIからデータ取得 (タイムアウトを長めに)
            res = await client.get(LAW_API_V2, timeout=30)
            res.raise_for_status()
            data = res.json()
            
            articles = data.get("law_full_text", {}).get("LawBody", {}).get("MainProvision", {}).get("Articles", [])
            title = f"🏛️ 日本国憲法 第{target_no}条"
            display_text = "指定された条文が見つかりませんでした。"

            for art in articles:
                if art.get("article_num") == str(target_no):
                    caption = art.get("article_caption", "")
                    paragraphs = art.get("paragraphs", [])
                    para_texts = []
                    for p in paragraphs:
                        sentences = p.get("sentences", [])
                        text = "".join([s.get("sentence_text", "") for s in sentences])
                        p_num = p.get("paragraph_num", "")
                        if p_num and p_num != "1":
                            para_texts.append(f"{p_num} {text}")
                        else:
                            para_texts.append(text)
                    display_text = f"**{caption}**\n\n" + "\n".join(para_texts)
                    break
            
            # 「考え中...」だったメッセージを編集(PATCH)して表示
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            payload = {
                "embeds": [{
                    "title": title,
                    "description": display_text[:1900],
                    "color": 0x3498DB
                }]
            }
            await client.patch(patch_url, json=payload)

        except Exception as e:
            print(f"Error: {e}")
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            await client.patch(patch_url, json={"content": f"エラーが発生しました: {e}"})

@app.post("/interactions")
async def interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    
    # 署名検証
    verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
    try:
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid request signature")

    data = await request.json()
    
    # 1. Pingへの応答
    if data.get("type") == 1:
        return {"type": 1}

    # 2. スラッシュコマンドへの応答
    if data.get("type") == 2:
        token = data.get("token")
        options = data.get("data", {}).get("options", [])
        target_no = "1"
        for opt in options:
            if opt.get("name") == "number":
                target_no = str(opt.get("value"))

        # 【ここが重要】バックグラウンドで処理を開始し、Discordには「考え中...」と即レスする
        asyncio.create_task(fetch_v2_and_edit_response(token, target_no))
        
        return {
            "type": 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
        }

    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
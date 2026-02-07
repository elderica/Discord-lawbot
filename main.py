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
            "options": [{"name": "number", "description": "条文番号（例：9）", "type": 3, "required": False}]
        }
        await client.post(url, headers=headers, json=payload)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok"}

# --- v2 JSON解析ロジック ---
async def fetch_v2_and_edit_response(token, target_no):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(LAW_API_V2, timeout=15)
            res.raise_for_status()
            data = res.json()
            
            # v2の階層を掘る
            articles = data.get("law_full_text", {}).get("LawBody", {}).get("MainProvision", {}).get("Articles", [])
            
            title = f"🏛️ 日本国憲法 第{target_no}条"
            display_text = "条文が見つかりませんでした。"

            for art in articles:
                # v2は article_num が "9" のように数字文字列で来るのでそのまま比較可能
                if art.get("article_num") == str(target_no):
                    caption = art.get("article_caption", "")
                    paragraphs = art.get("paragraphs", [])
                    para_texts = []
                    for p in paragraphs:
                        sentences = p.get("sentences", [])
                        text = "".join([s.get("sentence_text", "") for s in sentences])
                        # 項番号があれば振る
                        p_num = p.get("paragraph_num", "")
                        if p_num and p_num != "1":
                            para_texts.append(f"{p_num} {text}")
                        else:
                            para_texts.append(text)
                    
                    display_text = f"**{caption}**\n\n" + "\n".join(para_texts)
                    break
            
            # Discordへ反映
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            payload = {
                "embeds": [{
                    "title": title,
                    "description": display_text[:1800],
                    "color": 0x3498DB,
                    "footer": {"text": "e-Gov API v2 (JSON) / Koyeb Hosting"}
                }]
            }
            await client.patch(patch_url, json=payload)
        except Exception as e:
            print(f"Error: {e}")

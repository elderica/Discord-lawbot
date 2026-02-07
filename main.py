import os
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from contextlib import asynccontextmanager

# --- 設定 ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BASE_URL = "https://laws.e-gov.go.jp/api/2"

# 法令名エイリアス（通称 → 正式名称）
ALIASES = {
    "民法": "民法（明治二十九年法律第八十九号）",
    "刑法": "刑法（明治四十年法律第四十五号）",
    "憲法": "日本国憲法",
    "日本国憲法": "日本国憲法",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}

        # グローバルコマンドを全削除
        await client.put(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands",
            headers=headers,
            json=[]
        )

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
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok"}

async def fetch_law_data(token: str, law_name: str, target_no: str):
    async with httpx.AsyncClient() as client:
        try:
            # --- 法令名正規化 ---
            law_name = law_name.strip()
            law_name = ALIASES.get(law_name, law_name)

            # 1. 法令検索
            search_res = await client.get(
                f"{BASE_URL}/laws",
                params={"lawName": law_name},
                timeout=15
            )
            search_res.raise_for_status()
            search_data = search_res.json()

            law_infos = search_data.get("result", {}).get("law_infos", [])
            if not law_infos:
                raise Exception(f"「{law_name}」が見つかりませんでした。")

            law_id = law_infos[0]["law_id"]
            law_title = law_infos[0]["law_name"]

            # 2. 条文データ取得
            content_res = await client.get(
                f"{BASE_URL}/lawdata",
                params={"lawId": law_id},
                timeout=25
            )
            content_res.raise_for_status()
            content_data = content_res.json()

            main = (
                content_data
                .get("result", {})
                .get("law_full_text", {})
                .get("Law", {})
                .get("LawBody", {})
                .get("MainProvision", {})
            )

            articles = main.get("Articles", [])

            display_text = f"第{target_no}条が見つかりませんでした。"

            for art in articles:
                if art.get("ArticleNum") == str(target_no):
                    caption = art.get("ArticleCaption", "")
                    paragraphs = art.get("Paragraph", [])
                    if not isinstance(paragraphs, list):
                        paragraphs = [paragraphs]

                    lines = []
                    for p in paragraphs:
                        sentence = p.get("ParagraphSentence", {}).get("Sentence", "")
                        if isinstance(sentence, dict):
                            sentence = sentence.get("#text", "")
                        lines.append(sentence)

                    display_text = f"**{caption}**\n\n" + "\n".join(lines)
                    break

            # 3. Discord 応答更新
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={
                    "embeds": [{
                        "title": f"🏛️ {law_title}",
                        "description": f"### 第{target_no}条\n{display_text[:1800]}",
                        "color": 0x2ECC71,
                        "footer": {"text": "Powered by e-Gov API v2"}
                    }]
                }
            )

        except Exception as e:
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": f"⚠️ エラーが発生しました: {str(e)}"}
            )

@app.post("/interactions")
async def interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    if not signature or not timestamp:
        raise HTTPException(status_code=401)

    body = await request.body()
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            timestamp.encode() + body,
            bytes.fromhex(signature)
        )
    except:
        raise HTTPException(status_code=401)

    data = await request.json()

    # PING
    if data.get("type") == 1:
        return {"type": 1}

    # SLASH COMMAND
    if data.get("type") == 2:
        token = data["token"]
        options = data["data"].get("options", [])

        law_name = None
        target_no = None

        for opt in options:
            if opt["name"] == "name":
                law_name = opt["value"]
            elif opt["name"] == "number":
                target_no = str(opt["value"])

        if not law_name or not target_no:
            return {
                "type": 4,
                "data": {"content": "法令名と条文番号を指定してください。"}
            }

        asyncio.create_task(fetch_law_data(token, law_name, target_no))
        return {"type": 5}

    return {"status": "ok"}

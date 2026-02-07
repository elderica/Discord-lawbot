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

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "name": "law",
            "description": "法令を検索します",
            "options": [
                {"name": "name", "description": "法令名（例：民法、刑法）", "type": 3, "required": True},
                {"name": "number", "description": "条文番号（例：1）", "type": 3, "required": True}
            ]
        }
        await client.post(url, headers=headers, json=payload)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root(): return {"status": "ok"}

async def fetch_law_data(token, law_name, target_no):
    async with httpx.AsyncClient() as client:
        try:
            # 1. 法令名から LawId を検索
            search_res = await client.get(f"{BASE_URL}/laws?lawName={law_name}", timeout=10)
            search_data = search_res.json()
            law_infos = search_data.get("result", {}).get("law_infos", [])
            
            if not law_infos:
                raise Exception(f"「{law_name}」が見つかりませんでした。正式名称で試してください。")
            
            law_id = law_infos[0].get("law_id")
            law_title = law_infos[0].get("law_name")

            # 2. LawId を使って条文データを取得
            content_res = await client.get(f"{BASE_URL}/lawdata?lawId={law_id}", timeout=20)
            content_data = content_res.json()
            
            # API v2 の深い階層を掘り進む
            law_full_text = content_data.get("result", {}).get("law_full_text", {})
            # Articles（条文リスト）を探す（法律によって階層が微妙に異なるため柔軟に取得）
            law_body = law_full_text.get("Law", {}).get("LawBody", {})
            main_provision = law_body.get("MainProvision", {})
            
            # 階層が「章」などで分かれている場合もあるが、まずは直下のArticlesを探す
            articles = main_provision.get("Articles", [])
            
            display_text = f"第{target_no}条が見つかりませんでした。"
            for art in articles:
                if art.get("ArticleNum") == str(target_no):
                    caption = art.get("ArticleCaption", "")
                    # 段落の抽出
                    paragraphs = art.get("Paragraph", [])
                    if not isinstance(paragraphs, list): paragraphs = [paragraphs]
                    
                    lines = []
                    for p in paragraphs:
                        sentence = p.get("ParagraphSentence", {}).get("Sentence", "")
                        if isinstance(sentence, dict): sentence = sentence.get("#text", "")
                        lines.append(str(sentence))
                    
                    display_text = f"**{caption}**\n\n" + "\n".join(lines)
                    break

            # 3. Discordに結果を返す
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            await client.patch(patch_url, json={
                "embeds": [{
                    "title": f"🏛️ {law_title} 第{target_no}条",
                    "description": display_text[:1900],
                    "color": 0x2ECC71
                }]
            })

        except Exception as e:
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            await client.patch(patch_url, json={"content": f"エラー: {str(e)}"})

@app.post("/interactions")
async def interactions(request: Request):
    # 署名検証 (ここはそのまま)
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
    try:
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except:
        raise HTTPException(status_code=401)

    data = await request.json()
    if data.get("type") == 1: return {"type": 1}

    if data.get("type") == 2:
        token = data.get("token")
        options = data.get("data", {}).get("options", [])
        
        # 入力値を取得
        args = {opt["name"]: opt["value"] for opt in options}
        law_name = args.get("name")
        target_no = str(args.get("number"))

        # 非同期タスク開始
        asyncio.create_task(fetch_law_data(token, law_name, target_no))
        return {"type": 5}

    return {"status": "ok"}
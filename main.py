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
        # 古い設定を一度お掃除
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        global_url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
        await client.put(global_url, headers=headers, json=[])
        
        # 名前を「lawsearch」にして新規登録
        GUILD_ID = "1467465108690043016"
        guild_url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands"
        
        payload = {
            "name": "law_search", 
            "description": "法令を検索して条文を表示します",
            "options": [
                {"name": "name", "description": "法令名（例：民法）", "type": 3, "required": True},
                {"name": "number", "description": "条文番号（例：1）", "type": 3, "required": True}
            ]
        }
        await client.post(guild_url, headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}, json=payload)
    yield
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root(): return {"status": "ok"}

async def fetch_law_data(token, law_name, target_no):
    async with httpx.AsyncClient() as client:
        try:
            # 1. 法令名から LawId を検索
            search_res = await client.get(f"{BASE_URL}/laws?lawName={law_name}", timeout=15)
            search_res.raise_for_status()
            search_data = search_res.json()
            law_infos = search_data.get("result", {}).get("law_infos", [])
            
            if not law_infos:
                raise Exception(f"「{law_name}」が見つかりませんでした。正式名称で試してください。")
            
            # 最初に見つかった法令のIDと正式名称を取得
            law_id = law_infos[0].get("law_id")
            law_title = law_infos[0].get("law_name")

            # 2. LawId を使って条文データ(JSON)を取得
            content_res = await client.get(f"{BASE_URL}/lawdata?lawId={law_id}", timeout=25)
            content_res.raise_for_status()
            content_data = content_res.json()
            
            # API v2 のデータ構造から条文リスト(Articles)を抽出
            law_full_text = content_data.get("result", {}).get("law_full_text", {})
            law_body = law_full_text.get("Law", {}).get("LawBody", {})
            main_provision = law_body.get("MainProvision", {})
            
            # 法律によって階層が深くなる場合があるため、まず直下のArticlesを探す
            articles = main_provision.get("Articles", [])
            
            # 見つからない場合のデフォルト
            display_text = f"第{target_no}条が見つかりませんでした。この法令にはその番号の条文がないか、章の下に隠れている可能性があります。"
            
            # 指定された条文番号(ArticleNum)を探す
            for art in articles:
                if art.get("ArticleNum") == str(target_no):
                    caption = art.get("ArticleCaption", "")
                    paragraphs = art.get("Paragraph", [])
                    if not isinstance(paragraphs, list): paragraphs = [paragraphs]
                    
                    lines = []
                    for p in paragraphs:
                        sentence = p.get("ParagraphSentence", {}).get("Sentence", "")
                        # e-Gov特有の辞書形式(#text)に対応
                        if isinstance(sentence, dict): sentence = sentence.get("#text", "")
                        lines.append(str(sentence))
                    
                    display_text = f"**{caption}**\n\n" + "\n".join(lines)
                    break

            # 3. Discordのメッセージを更新（PATCH）
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            await client.patch(patch_url, json={
                "embeds": [{
                    "title": f"🏛️ {law_title}",
                    "description": f"### 第{target_no}条\n{display_text[:1800]}",
                    "color": 0x2ECC71,
                    "footer": {"text": "Powered by e-Gov API v2"}
                }]
            })

        except Exception as e:
            print(f"DEBUG Error: {str(e)}")
            patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
            await client.patch(patch_url, json={"content": f"⚠️ エラーが発生しました: {str(e)}"})

@app.post("/interactions")
async def interactions(request: Request):
    # 1. 署名検証（Discordからの正規リクエストか確認）
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    if not signature or not timestamp: raise HTTPException(status_code=401)
    
    body = await request.body()
    verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
    try:
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except:
        raise HTTPException(status_code=401)

    data = await request.json()
    
    # 2. Pingへの応答
    if data.get("type") == 1: return {"type": 1}

    # 3. スラッシュコマンドへの応答
    if data.get("type") == 2:
        token = data.get("token")
        options = data.get("data", {}).get("options", [])
        
        law_name = None
        target_no = None

        # optionsリストの中から 'name' と 'number' を正しく抽出
        for opt in options:
            name_label = opt.get("name")
            if name_label == "name":
                law_name = opt.get("value")
            elif name_label == "number":
                target_no = str(opt.get("value"))

        # 万が一どちらかが取得できなかった場合のガード
        if not law_name or not target_no:
            return {
                "type": 4,
                "data": {"content": "エラー：入力項目が足りません。法令名と条文番号を両方入力してください。"}
            }

        # 「考え中...」を表示させて非同期でAPIを叩きに行く
        asyncio.create_task(fetch_law_data(token, law_name, target_no))
        return {"type": 5}

    return {"status": "ok"}
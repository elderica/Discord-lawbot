import os
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from contextlib import asynccontextmanager
import json

# --- 設定 ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BASE_URL = "https://laws.e-gov.go.jp/api/2"

# 法令名エイリアス
ALIASES = {
    "民法": "民法",
    "憲法": "日本国憲法",
    "刑法": "刑法",
    "商法": "商法",
    "会社法": "会社法",
    "民事訴訟法": "民事訴訟法",
    "刑事訴訟法": "刑事訴訟法",
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

def find_article_recursive(data, target_num):
    """再帰的に条文を検索する関数"""
    if isinstance(data, dict):
        # Articlesが見つかった場合
        if "Articles" in data:
            articles = data["Articles"]
            if not isinstance(articles, list):
                articles = [articles]
            for art in articles:
                if art.get("ArticleNum") == str(target_num):
                    return art
        
        # Articleが直接見つかった場合
        if "Article" in data:
            article = data["Article"]
            if isinstance(article, list):
                for art in article:
                    if art.get("ArticleNum") == str(target_num):
                        return art
            elif isinstance(article, dict):
                if article.get("ArticleNum") == str(target_num):
                    return article
        
        # 各キーを再帰的に探索
        for value in data.values():
            result = find_article_recursive(value, target_num)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_article_recursive(item, target_num)
            if result:
                return result
    return None

async def fetch_law_data(token, law_name, target_no):
    async with httpx.AsyncClient() as client:
        try:
            # 1. キーワード検索（ヒット率重視）
            search_res = await client.get(f"{BASE_URL}/laws", params={"keyword": law_name}, timeout=15)
            search_data = search_res.json()
            
            # API v2 の検索結果から law_infos を安全に取得
            result = search_data.get("result", {})
            law_infos = result.get("law_infos")

            # law_infos がリストでない（1件だけの場合など）に対応
            if isinstance(law_infos, dict):
                law_infos = [law_infos]
            elif not isinstance(law_infos, list) or len(law_infos) == 0:
                raise Exception(f"「{law_name}」に一致する法令が見つかりませんでした。")

            # 最初の1件を使用
            law_id = law_infos[0].get("law_id")
            law_title = law_infos[0].get("law_name")
            
            if not law_id:
                raise Exception("法令IDの特定に失敗しました。")

            # 2. 条文データ取得
            content_res = await client.get(f"{BASE_URL}/lawdata", params={"lawId": law_id}, timeout=25)
            content_data = content_res.json()

            # 3. 再帰検索で条文を特定（前の find_article 関数を使用）
            article = find_article(content_data, target_no)

            if article:
                caption = article.get("ArticleCaption", f"第{target_no}条")
                # 文字列か辞書(#text)かを判定して抽出
                lines = []
                paragraphs = article.get("Paragraph", [])
                if not isinstance(paragraphs, list): paragraphs = [paragraphs]
                
                for p in paragraphs:
                    sentence_data = p.get("ParagraphSentence", {}).get("Sentence")
                    # sentence_dataがリスト、辞書、文字列のどれでも対応
                    if isinstance(sentence_data, list):
                        for s in sentence_data:
                            text = s.get("#text", s) if isinstance(s, dict) else s
                            if text: lines.append(str(text))
                    elif isinstance(sentence_data, dict):
                        text = sentence_data.get("#text", "")
                        if text: lines.append(str(text))
                    elif sentence_data:
                        lines.append(str(sentence_data))
                        
                display_text = "\n".join(lines)
            else:
                caption, display_text = f"第{target_no}条", "指定された条文が見つかりませんでした。"

            # 4. Discordに結果を返す
            await client.patch(f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                               json={
                                   "embeds": [{
                                       "title": f"🏛️ {law_title}",
                                       "description": f"### {caption}\n{display_text[:1800]}",
                                       "color": 0x2ECC71,
                                       "footer": {"text": "Powered by e-Gov API v2"}
                                   }]
                               })
        except Exception as e:
            await client.patch(f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                               json={"content": f"⚠️ エラーが発生しました: {str(e)}"})
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
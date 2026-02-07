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

# 法令名エイリアス（通称 → 正式名称）
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

async def fetch_law_data(token: str, law_name: str, target_no: str):
    async with httpx.AsyncClient() as client:
        try:
            # --- 法令名正規化 ---
            law_name_original = law_name.strip()
            law_name = ALIASES.get(law_name_original, law_name_original)

            print(f"\n{'='*60}")
            print(f"DEBUG: Starting search for '{law_name_original}' -> '{law_name}'")
            print(f"{'='*60}")

            # 1. 複数の検索方法を試す
            search_attempts = [
                ("lawName", law_name),
                ("lawName", law_name_original),
                ("lawTitle", law_name),
                ("lawTitle", law_name_original),
            ]

            law_infos = []
            for param_name, param_value in search_attempts:
                if law_infos:
                    break
                    
                try:
                    print(f"\nDEBUG: Trying {param_name}={param_value}")
                    search_res = await client.get(
                        f"{BASE_URL}/laws",
                        params={param_name: param_value},
                        timeout=15
                    )
                    print(f"DEBUG: Status code: {search_res.status_code}")
                    print(f"DEBUG: URL: {search_res.url}")
                    
                    search_data = search_res.json()
                    print(f"DEBUG: Response structure: {json.dumps(search_data, ensure_ascii=False, indent=2)[:500]}")
                    
                    law_infos = search_data.get("result", {}).get("law_infos", [])
                    if law_infos:
                        print(f"DEBUG: ✓ Found {len(law_infos)} law(s) with {param_name}={param_value}")
                        break
                    else:
                        print(f"DEBUG: ✗ No results with {param_name}={param_value}")
                except Exception as e:
                    print(f"DEBUG: Error with {param_name}={param_value}: {e}")
                    continue
            
            if not law_infos:
                # 最後の手段：APIドキュメントのサンプルURLを試す
                print(f"\nDEBUG: Trying direct API v1 style...")
                try:
                    # API v1 スタイルも試してみる
                    search_res = await client.get(
                        "https://laws.e-gov.go.jp/api/1/lawlists/2",
                        timeout=15
                    )
                    print(f"DEBUG: API v1 status: {search_res.status_code}")
                    print(f"DEBUG: API v1 response: {search_res.text[:500]}")
                except Exception as e:
                    print(f"DEBUG: API v1 also failed: {e}")
                
                raise Exception(
                    f"「{law_name_original}」が見つかりませんでした。\n"
                    f"試した検索: {law_name}\n"
                    f"使用可能な法令: 民法、刑法、憲法、商法、会社法など\n"
                    f"※APIの応答がログに出力されています"
                )

            law_id = law_infos[0]["law_id"]
            law_title = law_infos[0]["law_name"]
            
            print(f"\nDEBUG: ✓ Selected law_id={law_id}")
            print(f"DEBUG: ✓ Law title={law_title}")

            # 2. 条文データ取得
            print(f"\nDEBUG: Fetching law data for law_id={law_id}")
            content_res = await client.get(
                f"{BASE_URL}/lawdata",
                params={"lawId": law_id},
                timeout=25
            )
            content_res.raise_for_status()
            content_data = content_res.json()

            print(f"DEBUG: Law data retrieved, size={len(json.dumps(content_data))} bytes")

            # 再帰的に条文を検索
            print(f"DEBUG: Searching for article number {target_no}")
            article = find_article_recursive(content_data, target_no)

            if article:
                print(f"DEBUG: ✓ Article {target_no} found!")
                caption = article.get("ArticleCaption", f"第{target_no}条")
                paragraphs = article.get("Paragraph", [])
                if not isinstance(paragraphs, list):
                    paragraphs = [paragraphs]

                lines = []
                for p in paragraphs:
                    sentence = p.get("ParagraphSentence", {}).get("Sentence", "")
                    if isinstance(sentence, dict):
                        sentence = sentence.get("#text", "")
                    if sentence:
                        lines.append(str(sentence))

                display_text = "\n".join(lines) if lines else "（条文の内容が取得できませんでした）"
            else:
                print(f"DEBUG: ✗ Article {target_no} NOT found")
                # デバッグ：最初の数個の条文番号を表示
                sample_articles = []
                def collect_article_nums(data, depth=0, max_depth=10):
                    if depth > max_depth or len(sample_articles) >= 5:
                        return
                    if isinstance(data, dict):
                        if "ArticleNum" in data:
                            sample_articles.append(data["ArticleNum"])
                        for v in data.values():
                            collect_article_nums(v, depth+1, max_depth)
                    elif isinstance(data, list):
                        for item in data:
                            collect_article_nums(item, depth+1, max_depth)
                
                collect_article_nums(content_data)
                print(f"DEBUG: Available article numbers (sample): {sample_articles}")
                
                caption = f"第{target_no}条"
                display_text = f"指定された条文が見つかりませんでした。\n利用可能な条文例: {', '.join(sample_articles[:5])}"

            # 3. Discord 応答更新
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={
                    "embeds": [{
                        "title": f"🏛️ {law_title}",
                        "description": f"### {caption}\n{display_text[:1800]}",
                        "color": 0x2ECC71,
                        "footer": {"text": "Powered by e-Gov API v2"}
                    }]
                }
            )

        except httpx.TimeoutException:
            print(f"\nDEBUG: ✗ Timeout error")
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": "⚠️ タイムアウト: APIの応答に時間がかかりすぎています。"}
            )
        except httpx.HTTPStatusError as e:
            print(f"\nDEBUG: ✗ HTTP error: {e.response.status_code}")
            print(f"DEBUG: Response text: {e.response.text[:1000]}")
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": f"⚠️ API エラー: ステータスコード {e.response.status_code}"}
            )
        except Exception as e:
            print(f"\nDEBUG: ✗ Error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": f"⚠️ {str(e)}"}
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
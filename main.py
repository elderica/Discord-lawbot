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

def find_article_in_tree(node, target_num):
    """
    ツリー構造から指定番号のArticleを検索
    node: 辞書または配列
    target_num: 検索する条文番号（文字列）
    """
    if isinstance(node, dict):
        # Articleタグで、Num属性が一致するか確認
        if node.get("tag") == "Article":
            attr = node.get("attr", {})
            if attr.get("Num") == str(target_num):
                return node
        
        # childrenを再帰的に探索
        if "children" in node:
            result = find_article_in_tree(node["children"], target_num)
            if result:
                return result
    
    elif isinstance(node, list):
        for item in node:
            result = find_article_in_tree(item, target_num)
            if result:
                return result
    
    return None

def extract_article_text(article_node):
    """
    Articleノードからテキストを抽出
    """
    caption = ""
    paragraphs = []
    
    if not isinstance(article_node, dict):
        return caption, paragraphs
    
    children = article_node.get("children", [])
    
    for child in children:
        if not isinstance(child, dict):
            continue
        
        tag = child.get("tag")
        
        # ArticleCaption（条文の見出し）
        if tag == "ArticleCaption":
            caption_children = child.get("children", [])
            if caption_children and isinstance(caption_children[0], str):
                caption = caption_children[0]
        
        # Paragraph（段落）
        elif tag == "Paragraph":
            para_text = extract_paragraph_text(child)
            if para_text:
                paragraphs.append(para_text)
    
    return caption, paragraphs

def extract_paragraph_text(para_node):
    """
    Paragraphノードからテキストを抽出（再帰的）
    """
    if not isinstance(para_node, dict):
        return ""
    
    children = para_node.get("children", [])
    texts = []
    
    for child in children:
        if isinstance(child, str):
            texts.append(child)
        elif isinstance(child, dict):
            tag = child.get("tag")
            child_children = child.get("children", [])
            
            # Sentence, Item など、テキストを含む可能性のあるタグ
            for c in child_children:
                if isinstance(c, str):
                    texts.append(c)
                elif isinstance(c, dict):
                    # 再帰的に探索
                    sub_text = extract_paragraph_text(c)
                    if sub_text:
                        texts.append(sub_text)
    
    return "".join(texts)

async def fetch_law_data(token: str, law_name: str, target_no: str):
    async with httpx.AsyncClient() as client:
        try:
            # --- 法令名正規化 ---
            law_name_original = law_name.strip()
            law_name = ALIASES.get(law_name_original, law_name_original)

            print(f"\n{'='*60}")
            print(f"DEBUG: Searching for '{law_name}', article {target_no}")
            print(f"{'='*60}")

            # 1. 法令検索
            headers = {"Accept": "application/json"}
            
            search_url = f"{BASE_URL}/laws"
            params = {"lawName": law_name}
            
            print(f"DEBUG: GET {search_url} with params={params}")
            
            search_res = await client.get(
                search_url,
                params=params,
                headers=headers,
                timeout=20
            )
            
            print(f"DEBUG: Search status={search_res.status_code}")
            
            if search_res.status_code != 200:
                raise Exception(f"法令検索に失敗しました (status={search_res.status_code})")
            
            search_data = search_res.json()
            
            if "laws" not in search_data or len(search_data["laws"]) == 0:
                raise Exception(f"「{law_name}」に一致する法令が見つかりませんでした")
            
            # 最初の法令を取得
            first_law = search_data["laws"][0]
            law_info = first_law.get("law_info", {})
            revision_info = first_law.get("revision_info", {})
            
            law_id = law_info.get("law_id")
            law_title = revision_info.get("law_title", law_name)
            
            print(f"DEBUG: Found law_id={law_id}, law_title={law_title}")
            
            if not law_id:
                raise Exception("法令IDの取得に失敗しました")

            # 2. 条文データ取得
            print(f"DEBUG: Fetching lawdata for {law_id}")
            
            content_url = f"{BASE_URL}/lawdata/{law_id}"
            content_res = await client.get(
                content_url,
                headers=headers,
                timeout=25
            )
            
            print(f"DEBUG: Lawdata status={content_res.status_code}")
            
            if content_res.status_code != 200:
                raise Exception(f"条文データの取得に失敗しました (status={content_res.status_code})")
            
            content_data = content_res.json()
            
            # law_full_textから条文を検索
            law_full_text = content_data.get("law_full_text", {})
            
            print(f"DEBUG: Searching for article {target_no} in tree structure")
            article_node = find_article_in_tree(law_full_text, target_no)
            
            if article_node:
                print(f"DEBUG: Article {target_no} found!")
                caption, paragraphs = extract_article_text(article_node)
                
                if not caption:
                    caption = f"第{target_no}条"
                
                if paragraphs:
                    display_text = "\n".join(paragraphs)
                else:
                    display_text = "（条文の内容が取得できませんでした）"
            else:
                print(f"DEBUG: Article {target_no} NOT found")
                caption = f"第{target_no}条"
                display_text = "指定された条文が見つかりませんでした。条文番号を確認してください。"

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
            
            print(f"DEBUG: Response sent to Discord")

        except httpx.TimeoutException:
            print(f"DEBUG: Timeout error")
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": "⚠️ タイムアウト: APIの応答に時間がかかりすぎています。"}
            )
        except Exception as e:
            print(f"DEBUG: Error: {type(e).__name__}: {str(e)}")
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
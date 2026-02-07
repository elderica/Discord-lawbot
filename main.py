import os
import asyncio
import httpx
import unicodedata
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
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        # コマンド登録
        GUILD_ID = "1467465108690043016"
        payload = {
            "name": "law_search",
            "description": "法令を検索（例: 民法 1）",
            "options": [
                {"name": "name", "description": "法令名", "type": 3, "required": True},
                {"name": "number", "description": "条文番号", "type": 3, "required": True}
            ]
        }
        await client.post(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands",
            headers={**headers, "Content-Type": "application/json"},
            json=payload
        )
    yield

app = FastAPI(lifespan=lifespan)

# --- 柔軟性: 文字・数字の正規化 ---
def normalize_text(s):
    return unicodedata.normalize('NFKC', str(s))

# --- 再帰探索: 文章の抽出 ---
def get_all_text(obj):
    if isinstance(obj, str): return obj
    if isinstance(obj, list): return "".join([get_all_text(i) for i in obj])
    if isinstance(obj, dict): return get_all_text(obj.get("children", []))
    return ""

def find_article_in_tree(nodes, target_num):
    if not isinstance(nodes, list): return None
    target_num = normalize_text(target_num)
    for node in nodes:
        if not isinstance(node, dict): continue
        if node.get("tag") == "Article":
            if normalize_text(node.get("attr", {}).get("Num", "")) == target_num:
                return node
        res = find_article_in_tree(node.get("children"), target_num)
        if res: return res
    return None

# --- メインロジック: 3段構えの取得攻撃 ---
async def fetch_law_data(token, law_name, target_no):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            # 1. 検索API
            s_res = await client.get(f"{BASE_URL}/laws", params={"keyword": law_name}, timeout=15)
            s_data = s_res.json()
            laws = s_data.get("laws", [])
            if not laws:
                raise Exception(f"「{law_name}」は見つかりませんでした。")

            target = laws[0]
            # あなたが調べた「必須パラメータ候補」を全抽出
            law_id = target.get("law_info", {}).get("law_id")
            law_num = target.get("law_info", {}).get("law_num")
            law_rev_id = target.get("revision_info", {}).get("law_revision_id")
            law_title = target.get("revision_info", {}).get("law_title") or law_name

            # 2. 本文取得（波状攻撃）
            # あなたが調べた通り、いずれかを指定して200が返るまで試す
            content_data = None
            trials = []
            if law_rev_id: trials.append({"law_revision_id": law_rev_id})
            if law_id:     trials.append({"law_id": law_id})
            if law_num:    trials.append({"law_num": law_num})

            for params in trials:
                c_res = await client.get(f"{BASE_URL}/lawdata", params=params, timeout=30)
                if c_res.status_code == 200:
                    content_data = c_res.json()
                    break
            
            if not content_data:
                raise Exception("全IDを試しましたが404でした。APIの仕様かデータ不備です。")

            # 3. 解析
            root = content_data.get("law_full_text", {}).get("children", [])
            article_node = find_article_in_tree(root, target_no)

            if article_node:
                caption = "無題"
                lines = []
                for child in article_node.get("children", []):
                    if child.get("tag") == "ArticleCaption":
                        caption = get_all_text(child)
                    elif child.get("tag") == "Paragraph":
                        lines.append(get_all_text(child))
                desc = f"### {caption}\n" + "\n".join(lines)
            else:
                desc = f"第{target_no}条が見つかりませんでした。"

            # 4. 返信
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"embeds": [{"title": f"🏛️ {law_title}", "description": desc[:1950], "color": 0x3498DB}]}
            )

        except Exception as e:
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": f"⚠️ クソ仕様に抗いましたが失敗: {str(e)}"}
            )

@app.post("/interactions")
async def interactions(request: Request):
    sig, ts = request.headers.get("X-Signature-Ed25519"), request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(ts.encode() + body, bytes.fromhex(sig))
    except:
        raise HTTPException(status_code=401)
    
    data = await request.json()
    if data.get("type") == 1: return {"type": 1}
    if data.get("type") == 2:
        opts = {o["name"]: o["value"] for o in data["data"].get("options", [])}
        asyncio.create_task(fetch_law_data(data["token"], opts.get("name"), opts.get("number")))
        return {"type": 5}
    return {"status": "ok"}
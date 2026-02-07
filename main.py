import os
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from contextlib import asynccontextmanager

# --- 設定（環境変数から読み込み） ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BASE_URL = "https://laws.e-gov.go.jp/api/2"

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        # Discordスラッシュコマンドの登録
        GUILD_ID = "1467465108690043016"
        payload = {
            "name": "law_search",
            "description": "法令を検索して条文を表示します",
            "options": [
                {"name": "name", "description": "法令名（例：民法、国旗国歌法）", "type": 3, "required": True},
                {"name": "number", "description": "条文番号（例：1）", "type": 3, "required": True}
            ]
        }
        await client.post(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands",
            headers={**headers, "Content-Type": "application/json"},
            json=payload
        )
    yield

app = FastAPI(lifespan=lifespan)

# --- 1. ツリー構造から対象の条文(Article)を探し出す ---
def find_article_in_tree(nodes, target_num):
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        # tagが"Article"でNumが一致するか
        if node.get("tag") == "Article" and str(node.get("attr", {}).get("Num")) == str(target_num):
            return node
        # 子要素があればさらに深く探す
        res = find_article_in_tree(node.get("children"), target_num)
        if res:
            return res
    return None

# --- 2. 見つかった条文ノードからテキストを抽出する ---
def extract_text(node):
    caption = ""
    lines = []
    for child in node.get("children", []):
        if not isinstance(child, dict): continue
        tag = child.get("tag")
        
        # 見出し
        if tag == "ArticleCaption":
            caption = "".join([str(c) for c in child.get("children", []) if isinstance(c, str)])
        
        # 段落と本文
        if tag == "Paragraph":
            for p_child in child.get("children", []):
                if not isinstance(p_child, dict): continue
                # ParagraphSentence または Sentence から文字を拾う
                if p_child.get("tag") == "ParagraphSentence":
                    for s_child in p_child.get("children", []):
                        if isinstance(s_child, dict) and s_child.get("tag") == "Sentence":
                            text = "".join([str(t) for t in s_child.get("children", []) if isinstance(t, str)])
                            if text: lines.append(text)
                elif p_child.get("tag") == "Sentence":
                    text = "".join([str(t) for t in p_child.get("children", []) if isinstance(t, str)])
                    if text: lines.append(text)
    return caption or f"第{node.get('attr', {}).get('Num')}条", lines

# --- 3. メインの非同期処理 ---
async def fetch_law_data(token, law_name, target_no):
    async with httpx.AsyncClient() as client:
        try:
            # A. 法令をキーワード検索
            s_res = await client.get(f"{BASE_URL}/laws", params={"keyword": law_name}, timeout=15)
            s_data = s_res.json()
            laws = s_data.get("laws", [])
            if not laws:
                raise Exception(f"「{law_name}」は見つかりませんでした。")

            # B. IDの抽出（執念のフォールバック付き）
            target = laws[0]
            rev_info = target.get("revision_info", {})
            law_info = target.get("law_info", {})
            
            # revision_id(長い) -> law_id(短い) の順で探す
            law_id_to_query = rev_info.get("law_revision_id") or law_info.get("law_id")
            law_title = rev_info.get("law_title") or law_info.get("law_name") or law_name

            if not law_id_to_query:
                raise Exception("APIから有効な法令IDを取得できませんでした。")

            # C. 本文の取得（アンダースコアありの正しいパラメータ名を使用）
            # まずは履歴IDで試す
            p = {"law_revision_id": law_id_to_query} if "_" in law_id_to_query else {"law_id": law_id_to_query}
            c_res = await client.get(f"{BASE_URL}/lawdata", params=p, timeout=30)
            
            if c_res.status_code != 200:
                raise Exception(f"本文取得失敗 (status={c_res.status_code})")
            
            c_data = c_res.status_code == 200 and c_res.json()
            root_children = c_data.get("law_full_text", {}).get("children", [])

            # D. 解析とDiscord送信
            article_node = find_article_in_tree(root_children, target_no)
            if article_node:
                cap, txts = extract_text(article_node)
                desc = f"### {cap}\n" + "\n".join(txts)
            else:
                desc = f"第{target_no}条は見つかりませんでした。"

            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"embeds": [{"title": f"🏛️ {law_title}", "description": desc[:1900], "color": 0x2ECC71, "footer": {"text": "Powered by e-Gov API v2"}}]}
            )
        except Exception as e:
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original",
                json={"content": f"⚠️ エラー: {str(e)}"}
            )

# --- 4. Discord Interaction 受け口 ---
@app.post("/interactions")
async def interactions(request: Request):
    sig = request.headers.get("X-Signature-Ed25519")
    ts = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(ts.encode() + body, bytes.fromhex(sig))
    except:
        raise HTTPException(status_code=401)
    
    data = await request.json()
    if data.get("type") == 1:
        return {"type": 1}
    
    if data.get("type") == 2:
        opts = {o["name"]: o["value"] for o in data["data"].get("options", [])}
        asyncio.create_task(fetch_law_data(data["token"], opts.get("name"), opts.get("number")))
        return {"type": 5} # 「考え中...」を表示
    
    return {"status": "ok"}
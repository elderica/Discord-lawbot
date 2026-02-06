from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
import requests
import os

app = FastAPI()

# --- ここを自分の情報に書き換えてください ---
APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
# ---------------------------------------

@app.on_event("startup")
async def register_commands():
    print("🚀 登録プロセスを開始します...") # これを追加
    print(f"📡 使用する ID: {APPLICATION_ID}") # これを追加
    
    url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    
    payload = {
        "name": "law", 
        "description": "日本国憲法を取得します"
    }

    try:
        r = requests.post(url, headers=headers, json=payload)
        print(f"📡 Discord応答コード: {r.status_code}") # これを追加
        if r.status_code in [200, 201]:
            print("✅ コマンドの登録に成功しました！")
        else:
            print(f"❌ 登録失敗: {r.status_code}, {r.text}")
    except Exception as e:
        print(f"⚠️ 通信エラー: {e}")

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/interactions")
async def handle_interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    
    pk = os.getenv("DISCORD_PUBLIC_KEY")
    try:
        verify_key = VerifyKey(bytes.fromhex(pk))
        verify_key.verify(f'{timestamp}'.encode() + body, bytes.fromhex(signature))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()
    
    # PING応答
    if data.get("type") == 1:
        return {"type": 1}

    # コマンド実行 (登録した "law" コマンドに反応する)
    if data.get("type") == 2:
        res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/321CONSTITUTION")
        res.encoding = 'utf-8'
        
        import re
        # 1. まずタグを消す
        raw_text = re.sub('<[^>]*>', '', res.text)
        
        # 2. 検索エラーがないかチェック
        if "取得結果が０件" in raw_text:
            display_text = "⚠️ 法律が見つかりませんでした。"
        else:
            # 3. 「日本国憲法」という文字より後の「本文」だけを取り出す
            if "日本国憲法" in raw_text:
                # splitで分割して、最後の要素（本文）だけを採用
                body_text = raw_text.split("日本国憲法")[-1]
            else:
                body_text = raw_text
                
            # 4. 連続する空白や改行をスッキリさせる
            # \s+ は「1つ以上の空白・改行」を意味します。これをスペース1個に置換。
            display_text = re.sub(r'\s+', ' ', body_text).strip()[:1000]

        return {
            "type": 4,
            "data": {
                "content": f"📜 **日本国憲法 前文**\n\n{display_text}..."
            }
        }

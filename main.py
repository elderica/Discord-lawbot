from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
import requests
import os
import re

app = FastAPI()

APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")

@app.on_event("startup")
async def register_commands():
    url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    
    # 修正ポイント：コマンドに入力欄(options)を追加
    payload = {
        "name": "law", 
        "description": "日本国憲法の条文を表示します",
        "options": [
            {
                "name": "number",
                "description": "表示したい条文の番号（例：9）",
                "type": 3, 
                "required": False
            }
        ]
    }
    r = requests.post(url, headers=headers, json=payload)
    print(f"📡 コマンド登録結果: {r.status_code}")

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/interactions")
async def handle_interactions(request: Request):
    # --- 署名検証 (ここはそのまま) ---
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    try:
        verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
        verify_key.verify(f'{timestamp}'.encode() + body, bytes.fromhex(signature))
    except:
        raise HTTPException(status_code=401)

    data = await request.json()
    if data.get("type") == 1: return {"type": 1}

    # --- 実行処理 ---
    if data.get("type") == 2:
        # 1. ユーザーが入力した番号を取得（なければ「前文」とする）
        options = data["data"].get("options", [])
        target_no = options[0]["value"] if options else "前文"

        # 2. e-Gov APIからデータを取得
        res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/321CONSTITUTION")
        res.encoding = 'utf-8'
        xml_text = res.text

        # 3. 特定の条文を抜き出すロジック
        if target_no == "前文":
            title = "📜 日本国憲法 前文"
            # <Preamble>タグの中身を抜く
            match = re.search(r'<Preamble>(.*?)</Preamble>', xml_text, re.DOTALL)
            display_text = re.sub('<[^>]*>', '', match.group(1)) if match else "見つかりませんでした"
        else:
            # 「第九条」などの漢字ではなく、数字で検索しやすいように調整
            # ArticleTitle="第○条" を探す
            pattern = f'ArticleTitle="第{target_no}条".*?<ArticleSentence>(.*?)</ArticleSentence>'
            match = re.search(pattern, xml_text, re.DOTALL)
            
            if match:
                title = f"🏛️ 日本国憲法 第{target_no}条"
                display_text = re.sub('<[^>]*>', '', match.group(1))
            else:
                title = "⚠️ 検索エラー"
                display_text = f"第 {target_no} 条が見つかりませんでした。数字（1〜103）を入力してください。"

        # 4. 見やすく整形してEmbedで返す
        return {
            "type": 4,
            "data": {
                "embeds": [{
                    "title": title,
                    "description": re.sub(r'\s+', ' ', display_text).strip(),
                    "color": 0x3498db,
                    "footer": {"text": "e-Gov APIより取得"}
                }]
            }
        }
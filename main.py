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
    payload = {
        "name": "law", 
        "description": "日本国憲法の条文を表示します",
        "options": [{"name": "number", "description": "条文番号（例：9）", "type": 3, "required": False}]
    }
    requests.post(url, headers=headers, json=payload)

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/interactions")
async def handle_interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(f'{timestamp}'.encode() + body, bytes.fromhex(signature))
    except:
        raise HTTPException(status_code=401)

    data = await request.json()
    if data.get("type") == 1: return {"type": 1}

    if data.get("type") == 2:
        options = data["data"].get("options", [])
        target_no = options[0]["value"] if options else "前文"

        res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/321CONSTITUTION")
        res.encoding = 'utf-8'
        xml_text = res.text

        title = "⚠️ エラー"
        display_text = f"第 {target_no} 条が見つかりませんでした。"

        if target_no == "前文":
            title = "📜 日本国憲法 前文"
            match = re.search(r'<Preamble>(.*?)</Preamble>', xml_text, re.DOTALL)
            if match:
                display_text = re.sub('<[^>]*>', '', match.group(1))
        else:
            # 条文ごとに分割してループで探す
            articles = xml_text.split('<Article ')
            for art in articles:
                # ユーザーが入力した数字（例：9）が ArticleTitle="第9条" のように含まれているか
                if f'ArticleTitle="第{target_no}条"' in art:
                    title = f"🏛️ 日本国憲法 第{target_no}条"
                    # 本文を抜き出す
                    sentence_match = re.search(r'<ArticleSentence>(.*?)</ArticleSentence>', art, re.DOTALL)
                    if sentence_match:
                        display_text = re.sub('<[^>]*>', '', sentence_match.group(1))
                    break

        return {
            "type": 4,
            "data": {
                "embeds": [{
                    "title": title,
                    "description": re.sub(r'\s+', ' ', display_text).strip()[:2000],
                    "color": 0x3498db,
                    "footer": {"text": "e-Gov APIより取得"}
                }]
            }
        }
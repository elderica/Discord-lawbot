from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
import requests
import os
import re

app = FastAPI()

APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")

# 1〜103まで対応した漢数字変換
def to_kanji(n):
    try:
        n = int(n)
        kanji = {1:'一', 2:'二', 3:'三', 4:'四', 5:'五', 6:'六', 7:'七', 8:'八', 9:'九', 10:'十'}
        if n <= 10: return kanji[n]
        if n < 20: return "十" + (kanji[n%10] if n%10!=0 else "")
        if n < 100: return kanji[n//10] + "十" + (kanji[n%10] if n%10!=0 else "")
        if n < 110: return "百" + (kanji[n%10] if n%10!=0 else "")
        return str(n)
    except: return n

@app.on_event("startup")
async def register_commands():
    url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "name": "law", 
        "description": "日本国憲法を表示します",
        "options": [{"name": "number", "description": "条文番号（例：9）", "type": 3, "required": False}]
    }
    requests.post(url, headers=headers, json=payload)

@app.post("/interactions")
async def handle_interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()

    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            f'{timestamp}'.encode() + body,
            bytes.fromhex(signature)
        )
    except:
        raise HTTPException(status_code=401)

    data = await request.json()

    if data.get("type") == 1:
        return {"type": 1}

    if data.get("type") == 2:
        options = data["data"].get("options", [])
        target_no = options[0]["value"] if options else "前文"

        res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/321CONSTITUTION")
        res.encoding = 'utf-8'
        xml_text = res.text

        title = f"🏛️ 日本国憲法 第{target_no}条"
        display_text = "条文が見つかりませんでした。"

        if target_no == "前文":
            title = "📜 日本国憲法 前文"
            match = re.search(r'<Preamble>(.*?)</Preamble>', xml_text, re.DOTALL)
        else:
            k_no = to_kanji(target_no)
            pattern = rf'<Article>.*?<ArticleTitle>第{k_no}条</ArticleTitle>.*?<ArticleSentence>(.*?)</ArticleSentence>.*?</Article>'
            match = re.search(pattern, xml_text, re.DOTALL)

        if match:
            display_text = re.sub('<[^>]*>', '', match.group(1))

        return {
            "type": 4,
            "data": {
                "embeds": [{
                    "title": title,
                    "description": re.sub(r'\s+', ' ', display_text).strip()[:1800],
                    "color": 0x3498db,
                    "footer": {"text": "e-Gov APIより取得"}
                }]
            }
        }

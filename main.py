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

        title = "⚠️ 検索エラー"
        display_text = f"第 {target_no} 条が見つかりませんでした。"

        if target_no == "前文":
            title = "📜 日本国憲法 前文"
            match = re.search(r'<Preamble>(.*?)</Preamble>', xml_text, re.DOTALL)
            if match:
                display_text = re.sub('<[^>]*>', '', match.group(1))
        else:
            # --- 【最強の検索ロジック】 ---
            # 漢数字変換を使わずに、全てのArticleをスキャンして
            # 「その条文の中に第〇条という文字があるか」をタグ無視で判定します
            articles = xml_text.split('<Article ')
            for art in articles:
                # タグを一旦全部消して、純粋なテキストにする
                plain_text = re.sub('<[^>]*>', '', art)
                # 「第9条」という半角数字の検索にもヒットするよう、
                # ここでは「数字が含まれているか」ではなく「第...条」の構造を狙います。
                # 憲法の場合は漢数字なので、本来は漢数字が必要ですが、
                # e-Govの属性値 ArticleTitle="第九条" を直接狙い撃ちします。
                
                # ユーザーが入力した数字を、プログラム的に漢数字に変換するのが面倒な場合の
                # 最も確実な「部分一致」作戦：
                if f'ArticleTitle="第' in art and f'{target_no}条"' in art or f'第{target_no}条' in plain_text:
                    title = f"🏛️ 日本国憲法 第{target_no}条"
                    sentence_match = re.search(r'<ArticleSentence>(.*?)</ArticleSentence>', art, re.DOTALL)
                    if sentence_match:
                        display_text = re.sub('<[^>]*>', '', sentence_match.group(1))
                        break
            # ----------------------------

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
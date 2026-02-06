from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import requests
import json

app = FastAPI()

# 後でRenderの「Environment Variables」に設定します
PUBLIC_KEY = "" 

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/interactions")
async def handle_interactions(request: Request):
    # Discord認証
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    
    # 署名検証（Renderの環境変数から取得するように変更）
    import os
    pk = os.getenv("DISCORD_PUBLIC_KEY")
    try:
        VerifyKey(bytes.fromhex(pk)).verify(
            f'{timestamp}'.encode() + body, bytes.fromhex(signature)
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()
    
    # PING応答
    if data["type"] == 1:
        return {"type": 1}

    # e-Gov API 取得の「雑な仕様」を具現化（仮）
    if data["type"] == 2:
        # とりあえず日本国憲法を取得してみる
        res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/昭和二十二年憲法")
        return {
            "type": 4,
            "data": {"content": f"e-Gov API 接続成功！データ文字数: {len(res.text)}"}
        }

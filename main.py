from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey
import requests
import os

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "message": "Lawbot is running!"}

@app.post("/interactions")
async def handle_interactions(request: Request):
    # Discordからの署名ヘッダーを取得
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    
    # 署名がない場合は即座にエラー
    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="Missing signature headers")

    body = await request.body()
    
    # Renderの「Environment Variables」からPUBLIC KEYを取得
    pk = os.getenv("DISCORD_PUBLIC_KEY")
    
    if not pk:
        print("CRITICAL ERROR: DISCORD_PUBLIC_KEY is not set in Render environment variables!")
        raise HTTPException(status_code=500, detail="Server configuration error")

    # 署名検証の実行
    try:
        verify_key = VerifyKey(bytes.fromhex(pk))
        verify_key.verify(
            f'{timestamp}'.encode() + body, 
            bytes.fromhex(signature)
        )
    except Exception as e:
        print(f"Verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # リクエスト内容を解析
    data = await request.json()
    
    # 1. PING応答 (DiscordのURL検証用)
    if data.get("type") == 1:
        return {"type": 1}

    # 2. アプリケーションコマンド (スラッシュコマンドなど)
    if data.get("type") == 2:
        # e-Gov API を叩く処理
        try:
            # 昭和二十二年憲法（日本国憲法）を取得
            res = requests.get("https://elaws.e-gov.go.jp/api/1/lawdata/昭和二十二年憲法")
            res.raise_for_status()
            content = f"e-Gov API 接続成功！データ取得完了（文字数: {len(res.text)}）"
        except Exception as e:
            content = f"e-Gov API 連携エラー: {str(e)}"

        return {
            "type": 4,
            "data": {
                "content": content
            }
        }

    return {"type": 1} # デフォルト応答
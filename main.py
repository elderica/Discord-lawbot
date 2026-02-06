from bs4 import BeautifulSoup
import requests
import os
import re
import asyncio
from fastapi import FastAPI, Request, HTTPException
from nacl.signing import VerifyKey

app = FastAPI()

APPLICATION_ID = os.getenv("APPLICATION_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")

def to_kanji(n):
    try:
        n = int(n)
        kanji = {0:'', 1:'一', 2:'二', 3:'三', 4:'四', 5:'五', 
                 6:'六', 7:'七', 8:'八', 9:'九', 10:'十'}
        if n <= 10: 
            return kanji[n]
        if n < 20: 
            return "十" + kanji[n % 10]
        if n < 100: 
            return kanji[n // 10] + "十" + kanji[n % 10]
        return str(n)
    except: 
        return str(n)

@app.get("/")
async def root():
    return {"status": "ok"}

async def fetch_and_edit_response(token, target_no):
    try:
        res = requests.get(
            "https://elaws.e-gov.go.jp/api/1/lawdata/321CONSTITUTION",
            timeout=10
        )
        res.raise_for_status()
        res.encoding = "utf-8"
        
        soup = BeautifulSoup(res.text, 'xml')
        
        title = f"🏛️ 日本国憲法 第{target_no}条"
        display_text = "条文が見つかりませんでした。"
        
        if target_no == "前文":
            title = "📜 日本国憲法 前文"
            preamble = soup.find('Preamble')
            if preamble:
                display_text = preamble.get_text(strip=True)
        else:
            k_no = to_kanji(target_no)
            
            # 複数の方法で検索
            article = None
            
            # 方法1: ArticleTitle属性で検索
            article = soup.find('Article', {'ArticleTitle': f'第{k_no}条'})
            
            # 方法2: ArticleTitle要素で検索
            if not article:
                for art in soup.find_all('Article'):
                    title_elem = art.find('ArticleTitle')
                    if title_elem and f'第{k_no}条' in title_elem.get_text():
                        article = art
                        break
            
            # 方法3: Num属性で検索
            if not article:
                article = soup.find('Article', {'Num': str(target_no)})
            
            if article:
                # ArticleCaption（条文の見出し）を取得
                caption = article.find('ArticleCaption')
                caption_text = f"【{caption.get_text(strip=True)}】\n" if caption else ""
                
                # Paragraphから本文を取得
                paragraphs = article.find_all('Paragraph')
                para_texts = []
                for para in paragraphs:
                    para_num = para.get('Num', '')
                    sentences = para.find_all('Sentence')
                    if sentences:
                        para_text = ''.join([s.get_text(strip=True) for s in sentences])
                        if para_num and para_num != '1':
                            para_texts.append(f"{para_num}. {para_text}")
                        else:
                            para_texts.append(para_text)
                
                if para_texts:
                    display_text = caption_text + '\n'.join(para_texts)
        
        # Discordメッセージを更新
        patch_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{token}/messages/@original"
        payload = {
            "embeds": [{
                "title": title,
                "description": display_text[:4000],
                "color": 0x3498DB,
                "footer": {"text": "e-Gov APIより取得"}
            }]
        }
        response = requests.patch(patch_url, json=payload, timeout=10)
        response.raise_for_status()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

@app.post("/interactions")
async def handle_interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()
    
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            timestamp.encode() + body, bytes.fromhex(signature)
        )
    except:
        raise HTTPException(status_code=401)
    
    data = await request.json()
    
    if data.get("type") == 1:
        return {"type": 1}
    
    if data.get("type") == 2:
        token = data.get("token")
        options = data["data"].get("options", [])
        target_no = options[0]["value"] if options else "前文"
        
        asyncio.create_task(fetch_and_edit_response(token, target_no))
        return {"type": 5}

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

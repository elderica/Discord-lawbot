# 1. 最小限のPython環境（slim）を使う（メモリ節約の基本）
FROM python:3.11-slim

# 2. コンテナ内の作業ディレクトリを決定
WORKDIR /app

# 3. 依存関係のインストール（ここがエラーの温床）
# まず requirements.txt だけコピーしてキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 残りのコードをコピー
COPY . .

# 5. 実行（main.py はあなたのファイル名に合わせてください）
CMD ["python", "main.py"]
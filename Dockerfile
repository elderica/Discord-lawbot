# 1. フルセットのPython 3.11（全部入り）を使う
FROM python:3.11

# 2. 作業ディレクトリ設定
WORKDIR /app

# 3. 依存関係のインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. コードをコピー
COPY . .

# 5. 実行
CMD ["python", "main.py"]
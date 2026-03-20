# Document AI Relay API

Bubble から送信された画像または PDF を Google Document AI に中継する FastAPI 実装です。`application/json` による `file_url` 指定と、`multipart/form-data` によるファイル直接アップロードの両方に対応しています。

## エンドポイント

- `POST /document-ai/process` : 既存互換の全生データレスポンス
- `POST /document-ai/process/raw` : Document AI の全生データレスポンス
- `POST /document-ai/process/fields` : `field` / `value` / `confidence` のみを返す省略レスポンス
- `GET /health`

## リクエスト例

すべての POST エンドポイントは同じ入力形式を利用できます。

### 1. JSON でファイル URL を送る場合

```json
{
  "file_url": "https://example.com/sample.jpg",
  "mime_type": "image/jpeg",
  "project_id": "677366504119",
  "location": "us",
  "processor_id": "ab6edd358c275ddb",
  "processor_version": "optional-version-id"
}
```

### 2. multipart/form-data でファイルを直接送る場合

| フィールド | 必須 | 内容 |
| --- | --- | --- |
| file | 必須 | 解析対象の JPEG / PNG / PDF ファイル |
| project_id | 必須 | Google Cloud の project 識別子 |
| location | 必須 | Processor のロケーション |
| processor_id | 必須 | 利用する Processor ID |
| processor_version | 任意 | 利用する Processor Version ID |
| mime_type | 任意 | 未指定時はアップロードファイルの Content-Type を利用 |

Bubble からは API Connector で `multipart/form-data` を使い、`file` にアップロード済み画像を渡せます。

## レスポンス

### 1. 全生データ取得用 (`/document-ai/process` または `/document-ai/process/raw`)

```json
{
  "document": {
    "...": "Document AI の生データ"
  }
}
```

### 2. 省略取得用 (`/document-ai/process/fields`)

```json
{
  "fields": [
    {
      "field": "invoice_id",
      "value": "12345",
      "confidence": 0.98
    }
  ]
}
```

- `fields` は `document.entities` を汎用的に走査して生成するため、Processor 側でフィールドが追加・削除されても API コードの個別修正は不要です。
- ネストした `properties` も `parent.child` 形式で展開します。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Docker / Cloud Run

Cloud Build がルートの `Dockerfile` を参照してイメージをビルドできるようにしています。

```bash
docker build -t document-ai-relay .
docker run --rm -p 8080:8080 -e PORT=8080 document-ai-relay
```

## 仕様メモ

- 対応 MIME type は `image/jpeg`、`image/png`、`application/pdf` のみです。
- `processor_version` が未指定の場合は Processor のデフォルト version を利用します。
- 全生データ用パスは Document AI の protobuf を JSON 化した内容をそのまま返します。
- 省略用パスは `document.entities` を元に `field` / `value` / `confidence` だけを抽出して返します。
- Google 認証情報はサーバー側環境変数または Workload Identity などで管理してください。
- `Content-Type` は `application/json` または `multipart/form-data` のみ受け付けます。

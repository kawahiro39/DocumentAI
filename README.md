# Document AI Relay API

Bubble から送信された画像または PDF の URL を取得し、Google Document AI にそのまま中継する FastAPI 実装です。

## エンドポイント

- `POST /document-ai/process`
- `GET /health`

## リクエスト例

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

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 仕様メモ

- 対応 MIME type は `image/jpeg`、`image/png`、`application/pdf` のみです。
- `processor_version` が未指定の場合は Processor のデフォルト version を利用します。
- レスポンスは `{"document": ...}` 形式で返し、`document` の中身は Document AI の protobuf を JSON 化した内容をそのまま返します。
- Google 認証情報はサーバー側環境変数または Workload Identity などで管理してください。

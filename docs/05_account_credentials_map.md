# アカウント連携情報マップ

最終更新: 2026-05-04

## 使用アカウント一覧

| サービス | アカウント | 用途 | 課金 |
|---|---|---|---|
| **Google Cloud Platform** | denanokk@gmail.com | Gemini API（プロジェクト: denkaishitsu-906） | Tier 1 後払い |
| **Google AI Studio** | 同上 | Gemini API キー発行 | 同上 |
| **Google Drive** | 専用アカウント（ai.whats.up.news@gmail.com） | mp3/digest 保管 | 無料 |
| **GitHub** | denanokk-hmt | コード管理 + Pages配信 | 無料 |
| **Spotify for Creators** | 専用アカウント | Podcast配信ハブ | 無料 |
| **Apple Podcasts Connect** | 専用アカウント（Apple ID） | Apple配信 | 無料 |
| **Slack** | （ユーザー個人ワークスペース） | 通知受信 | 無料 |

## サービス別 詳細

### 1. Gemini API（GCP）

| 項目 | 値 |
|---|---|
| プロジェクト | `denkaishitsu-906` |
| 課金アカウント | `01C568-D87153-793A5F` |
| Tier | Tier 1（後払い） |
| API Key 末尾 | `...DRtQ`（`.env` の `GEMINI_API_KEY`） |
| 使用モデル | gemini-3.1-pro-preview（収集/台本）、gemini-3.1-flash-tts-preview（音声）、gemini-3.1-flash-image-preview（エピソード画像）、gemini-3-pro-image-preview（カバー） |
| 月額目安 | $6〜$15 |

### 2. Google Drive

| 項目 | 値 |
|---|---|
| アカウント | `ai.whats.up.news@gmail.com`（専用） |
| OAuth Client | denkaishitsu-906プロジェクトで発行 |
| credentials.json | プロジェクトルートに配置（git管理外） |
| gdrive_token.json | 初回OAuth後に自動生成（git管理外） |
| スコープ | `drive.file`（自分が作ったファイルのみ操作） + `userinfo.email` |
| 保存場所 | `My Drive/AI What's Up News/YYYY/MM/YYYY-MM-DD/` |

### 3. GitHub

| 項目 | 値 |
|---|---|
| アカウント | `denanokk-hmt` |
| リポジトリ | `denanokk-hmt/ai-news-whats-up` |
| ブランチ構成 | `main`（コード）、`gh-pages`（配信） |
| Pages URL | `https://denanokk-hmt.github.io/ai-news-whats-up/` |
| 認証 | SSH鍵（Mac/Mac Mini ~/.ssh/） |

### 4. Spotify for Creators

| 項目 | 値 |
|---|---|
| アカウント | 専用アカウント |
| 番組URL | `https://open.spotify.com/show/6xRPLxCUdwPObmS4gpnU5n` |
| RSS フィード | `https://denanokk-hmt.github.io/ai-news-whats-up/feed.xml` |
| 移行元ホスト指定 | "Somewhere else" |

### 5. Apple Podcasts Connect

| 項目 | 値 |
|---|---|
| Apple ID | 専用アカウント（メール: ai.whats.up.news@gmail.com） |
| Connect URL | `https://podcastsconnect.apple.com/my-podcasts/show/ai-whats-up-news/355b7de7-72b3-4545-b059-ef8ccf302f54` |
| RSS フィード | `https://denanokk-hmt.github.io/ai-news-whats-up/feed.xml` |
| 番組ID | 審査完了後に発行 |

### 6. Slack Webhook

| 項目 | 値 |
|---|---|
| Webhook URL | `.env` の `SLACK_WEBHOOK_URL`（公開禁止） |
| 注意 | URL自体が認証情報。コード/ログに出さない |

## シークレット管理ルール

### 配置場所（git管理外）

```
.env                  # GEMINI_API_KEY, SLACK_WEBHOOK_URL
credentials.json      # Google OAuth Client
gdrive_token.json     # Google OAuth Token（自動生成）
```

### 禁止事項

- これらファイルの中身を `cat` 等で出力しない
- コード内にハードコードしない
- スクリーンショットや会話に含めない
- `git add` で誤ってコミットしない（.gitignore 設定済み）

### ローテーション必要時

| シークレット | ローテーション手順 |
|---|---|
| GEMINI_API_KEY | Google AI Studio で削除→新規発行→`.env` 更新 |
| SLACK_WEBHOOK_URL | Slack Apps で旧Webhook削除→新規発行→`.env` 更新 |
| credentials.json | GCP Console で OAuth Client 再発行→ `gdrive_token.json` 削除→次回OAuth再認証 |

## 認証フロー（初回セットアップ時）

```
1. .env 作成（GEMINI_API_KEY, SLACK_WEBHOOK_URL を手動記入）
2. credentials.json を GCP Console からダウンロード→配置
3. 初回 main.py 実行時:
     - GDrive 用 OAuth ブラウザ起動
     - 専用アカウントでサインイン → 同意 → token.json 自動生成
4. 以降は token.json で自動認証（90日でリフレッシュ）
```

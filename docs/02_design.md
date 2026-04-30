# 設計書: AI Daily What's up

最終更新: 2026-04-28

## 1. システム全体図

```
        ┌─────────────────────────────────────────┐
        │  macOS launchd  (毎朝 07:00 JST)         │
        └────────────────┬────────────────────────┘
                         ▼
        ┌─────────────────────────────────────────┐
        │  src/main.py  (オーケストレーター)        │
        └────────────────┬────────────────────────┘
                         ▼
   ┌─────────────────────────────────────────────────┐
   │  Phase 1: 収集  (Gemini 3.1 Pro + Google Search) │
   │  → 国内外AIニュース取得・翻訳・要約・ジャンル分類    │
   └────────────────┬────────────────────────────────┘
                    ▼
        ┌──────────────────────────┐
        │  Phase 2: 重複排除         │
        │  (SQLite で過去30日と照合) │
        └────────────────┬─────────┘
                         ▼
        ┌──────────────────────────┐
        │  Phase 3: 台本生成        │
        │  (Gemini 3.1 Pro)         │
        │  → 男女2人の対話シナリオ    │
        └────────────────┬─────────┘
                         ▼
        ┌──────────────────────────┐
        │  Phase 4: 音声生成        │
        │  (Gemini 2.5 Native Audio)│
        │  → mp3                   │
        └────────────────┬─────────┘
                         ▼
   ┌─────────────────────────────────────┐
   │  Phase 5: 配信                       │
   │  ├ Markdown生成                      │
   │  ├ Google Drive アップロード         │
   │  ├ GitHub Pages: mp3配置・RSS更新    │
   │  │    (Spotify はRSSから自動取得)    │
   │  └ Slack通知                         │
   └──────────────────────────────────────┘
```

## 2. ディレクトリ構成

```
ai-news-whats-up/
├── pyproject.toml
├── config.yaml
├── .env                          # ユーザー管理（Claudeは触らない）
├── .env.example
├── .gitignore
├── README.md
├── docs/
│   ├── 01_requirements.md
│   ├── 02_design.md
│   └── 03_task_procedure.md
├── data/
│   └── state.db                  # SQLite (重複排除用)
├── output/
│   └── 2026-04-28/
│       ├── articles.json         # 収集記事の生データ
│       ├── script.txt            # 対話台本
│       ├── episode.mp3           # 完成音声
│       └── digest.md             # Markdownダイジェスト
├── podcast/                      # GitHub Pagesリポジトリ（別管理）
│   ├── feed.xml                  # Podcast RSS
│   └── episodes/
│       └── 2026-04-28.mp3
├── src/
│   ├── main.py                   # オーケストレーター
│   ├── config.py                 # 設定ロード
│   ├── collector.py              # Phase 1: ニュース収集
│   ├── dedup.py                  # Phase 2: 重複排除
│   ├── script_generator.py       # Phase 3: 台本生成
│   ├── audio_generator.py        # Phase 4: 音声生成
│   ├── markdown_generator.py     # Markdownダイジェスト
│   ├── storage/
│   │   ├── gdrive.py             # GDrive アップロード
│   │   └── github_pages.py       # mp3配置 + RSS更新
│   └── notifiers/
│       └── slack.py              # Slack Webhook
├── tests/
└── com.takahiro.ainews.plist     # launchd設定
```

## 3. 各モジュール仕様

### 3.1 collector.py（ニュース収集）

**入力**: なし（時刻ベース）
**出力**: `output/YYYY-MM-DD/articles.json`

**処理**:
- Gemini 3.1 Pro + Google Search grounding を使用
- 過去24時間（前日19:00〜当日06:00 JST）対象
- 海外記事はタイトル・要約を日本語に翻訳
- ジャンルを自動判定
- 重要度を1-5で採点

**プロンプト概要**:
```
過去24時間（前日19:00〜当日06:00 JST）の国内外AI関連ニュースを網羅的に収集してください。

JSON形式で出力:
[
  {
    "url": "...",
    "original_title": "...",
    "japanese_title": "...",
    "source": "...",
    "published_at": "ISO8601",
    "summary_ja": "2-3文の日本語要約",
    "genre": "LLM/規制/資金調達/研究/製品/国内/その他",
    "importance": 1-5
  },
  ...
]
```

### 3.2 dedup.py（重複排除）

**入力**: `articles.json`
**出力**: 新規記事のみのリスト

**処理**:
- SQLiteの `seen_articles` テーブルに照合（過去30日）
- URL正規化 + ハッシュで判定
- 一致しないものだけ通す
- 通ったものは `seen_articles` に追加
- 30日より古いレコードはパージ

```sql
CREATE TABLE seen_articles (
  url_hash TEXT PRIMARY KEY,
  title TEXT,
  source TEXT,
  first_seen_at TEXT
);
```

### 3.3 script_generator.py（台本生成）

**入力**: 記事リスト
**出力**: `output/YYYY-MM-DD/script.txt`

**処理**:
- Gemini 3.1 Pro に台本生成プロンプト

**プロンプト概要**:
```
以下のニュースを元に、男性ホストTAKUと女性ホストMIOによる
ポッドキャスト「AI Daily What's up」の台本を5-10分（約2000-3500字）で作成。

要件:
- 自然な対話、適度な相槌、専門用語は短く解説
- オープニング: "おはようございます、AI Daily What's upです"
- クロージング: "それではまた明日、よい一日を"
- 形式: TAKU: ...\nMIO: ...
```

### 3.4 audio_generator.py（音声生成）

**入力**: `script.txt`
**出力**: `output/YYYY-MM-DD/episode.mp3`

**処理**:
- `gemini-2.5-flash-preview-native-audio-dialog` を使用
- multi-speaker config:
  - Speaker "TAKU": 男性音声（候補: Achernar, Schedar 等）
  - Speaker "MIO": 女性音声（候補: Aoede, Kore 等）
- 出力WAVをffmpegでmp3に変換

**前提**: ffmpeg のインストール（`brew install ffmpeg`）

### 3.5 markdown_generator.py

**入力**: 記事リスト + 台本
**出力**: `output/YYYY-MM-DD/digest.md`

**フォーマット**:
```markdown
# AI Daily What's up - 2026-04-28

## 🎙️ 本日のエピソード
[Spotifyリンク] | [GDrive mp3]

## 📋 トピック一覧（ジャンル別）

### LLM
- [タイトル](url) - VentureBeat ⭐⭐⭐⭐⭐
  > 要約...

### 規制・政策
...

## 🎬 台本全文
[台本]
```

### 3.6 storage/gdrive.py

**処理**:
- フォルダ構成: `AI Daily What's up / YYYY / MM / YYYY-MM-DD/`
- `episode.mp3` と `digest.md` をアップロード
- 共有リンクを取得

### 3.7 storage/github_pages.py

**処理**:
1. `podcast/episodes/YYYY-MM-DD.mp3` にコピー
2. `podcast/feed.xml`（RSS）に新エピソード追記
3. `git commit -am "Episode YYYY-MM-DD"` → `git push origin gh-pages`
4. Spotify for Podcasters は登録済みRSSから自動取得

**RSSフィード形式**:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>AI Daily What's up</title>
    <link>https://USERNAME.github.io/ai-news-whats-up/</link>
    <description>毎朝7時、男女2人がお届けする国内外AIニュース</description>
    <language>ja-jp</language>
    <itunes:author>takahiro</itunes:author>
    <itunes:category text="Technology"/>
    <item>
      <title>2026-04-28 AIニュース</title>
      <description>本日のトピック...</description>
      <pubDate>Mon, 28 Apr 2026 07:00:00 +0900</pubDate>
      <enclosure url="https://USERNAME.github.io/ai-news-whats-up/episodes/2026-04-28.mp3"
                 type="audio/mpeg" length="..."/>
      <guid>2026-04-28</guid>
    </item>
  </channel>
</rss>
```

### 3.8 notifiers/slack.py

**処理**:
- Slack Incoming Webhook
- Block Kit形式で投稿
  - ヘッダー: 「🎙️ AI Daily What's up - 2026-04-28」
  - 本日のトピック（5件のヘッドライン）
  - ボタン: [🎧 聴く（Spotify）] [📄 詳細を読む（GDrive）]

## 4. データフロー

```
[Gemini 3.1 Pro + Search]
        │
        ▼
articles.json ──┬─→ dedup → 新規記事
                │              │
                │              ├─→ [Gemini 3.1 Pro] → script.txt
                │              │              │
                │              │              ▼
                │              │     [Gemini 2.5 Native Audio] → episode.mp3
                │              │                                      │
                ▼              ▼                                      ▼
          markdown_generator ←─────────────────────────────────────────┤
                │                                                      │
                ▼                                                      │
              digest.md                                                │
                │                                                      │
        ┌───────┴────────┐                                             │
        ▼                ▼                                             │
     GDrive        GitHub Pages ←──────────────────────────────────────┘
                          │
                          ▼ (RSS経由)
                       Spotify
                          │
                          ▼
                       Slack通知
```

## 5. 設定ファイル（config.yaml）

```yaml
podcast:
  title: "AI Daily What's up"
  description: "毎朝7時、男女2人がお届けする国内外AIニュース"
  language: "ja-jp"
  author: "takahiro"

schedule:
  run_time: "07:00"
  timezone: "Asia/Tokyo"
  collection_window_hours: 24

gemini:
  collection_model: "gemini-3.1-pro-preview"
  script_model: "gemini-3.1-pro-preview"
  audio_model: "gemini-2.5-flash-preview-native-audio-dialog"

speakers:
  - name: "TAKU"
    role: "男性ホスト"
    voice: "Achernar"
  - name: "MIO"
    role: "女性ホスト"
    voice: "Aoede"

episode:
  target_minutes: [5, 10]
  target_chars: [2000, 3500]

storage:
  gdrive:
    root_folder: "AI Daily What's up"
  github:
    repo: "USERNAME/ai-news-whats-up"
    branch: "gh-pages"
    pages_url: "https://USERNAME.github.io/ai-news-whats-up"

notifications:
  slack:
    enabled: true
    webhook_url: "${SLACK_WEBHOOK_URL}"

dedup:
  retention_days: 30
  db_path: "data/state.db"
```

## 6. シークレット管理（重要）

ユーザーが `.env` を直接編集する。Claude/コードからは**読み書き禁止**：

```
# .env （ユーザー専用、Claudeは触らない）
GEMINI_API_KEY=...
GOOGLE_DRIVE_OAUTH_TOKEN=...
SLACK_WEBHOOK_URL=...
GITHUB_TOKEN=...
```

過去にAPIキー流出インシデントが発生したため、シークレットの取り扱いはユーザーが手動で行う。

## 7. エラー処理方針

| エラー | 対応 |
|---|---|
| Gemini APIタイムアウト | 3回リトライ → Slackに失敗通知 |
| 記事0件 | 「本日大きなニュースなし」エピソードを生成 |
| 音声生成失敗 | 台本だけ配信、Slackに警告 |
| GDrive/GitHub失敗 | ローカル保持、次回再試行 |

## 8. 依存サービス・ツール

| 種別 | 名称 | 用途 |
|---|---|---|
| API | Gemini 3.1 Pro Preview | 収集・翻訳・台本 |
| API | Gemini 2.5 Flash Native Audio | 音声合成 |
| API | Google Drive API v3 | mp3/Markdown保管 |
| API | Slack Incoming Webhook | 通知 |
| API | GitHub API（git push） | RSS/mp3配信 |
| サービス | Spotify for Podcasters | Podcast配信 |
| ツール | ffmpeg | WAV→mp3変換 |
| ツール | macOS launchd | スケジュール実行 |
| ライブラリ | google-genai | Gemini SDK |
| ライブラリ | google-api-python-client | GDrive |
| ライブラリ | feedgen | RSS生成 |
| ライブラリ | sqlite-utils | 重複排除 |

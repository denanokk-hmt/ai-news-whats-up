# AI What's Up News

毎朝7時、男女2名のホストがお届けする国内外AIニュースのPodcast自動生成システム。

## 公開先

| プラットフォーム | URL |
|---|---|
| Spotify | https://open.spotify.com/show/6xRPLxCUdwPObmS4gpnU5n |
| RSS Feed | https://denanokk-hmt.github.io/ai-news-whats-up/feed.xml |
| Apple Podcasts | （審査完了後に発行） |

## 特徴

- 毎朝07:00 JST に自動配信（Mac Miniでlaunchd運用）
- Gemini 3.1 Pro + Google Search で過去24時間の国内外AIニュースを自動収集
- 海外記事は自動で日本語に翻訳・要約
- ジャンル別に分類（LLM/規制/資金調達/研究/製品/国内）
- Gemini 3.1 Flash TTS で男女2名（Sadachbia/Laomedeia）の対話形式音声を生成
- 各エピソードに当日トピック反映の画像を自動生成
- Google Drive に永続保管 + Slack通知

## ドキュメント

| 文書 | 内容 |
|---|---|
| [01_requirements.md](docs/01_requirements.md) | 要件定義書 |
| [02_design.md](docs/02_design.md) | 設計書 |
| [03_task_procedure.md](docs/03_task_procedure.md) | 構築タスク手順 |
| [04_system_architecture.md](docs/04_system_architecture.md) | システム構成図 |
| [05_account_credentials_map.md](docs/05_account_credentials_map.md) | アカウント連携情報 |
| [06_operations_manual.md](docs/06_operations_manual.md) | 運用手順書 |
| [07_setup_guide.md](docs/07_setup_guide.md) | 新環境セットアップ |

## クイックスタート

```bash
# 環境構築（詳細は docs/07_setup_guide.md）
python3.12 -m venv .venv
.venv/bin/pip install -e .

# シークレット配置（手動）
cp .env.example .env       # GEMINI_API_KEY, SLACK_WEBHOOK_URL を記入
# credentials.json を Google Cloud Console から取得して配置

# 手動実行
PYTHONPATH=. .venv/bin/python -m src.main
```

## 構成

```
ai-news-whats-up/
├── docs/                # 設計・運用ドキュメント
├── src/                 # ソースコード
│   ├── main.py          # オーケストレーター
│   ├── collector.py     # ニュース収集（Gemini + Google Search）
│   ├── dedup.py         # 重複排除（SQLite）
│   ├── script_generator.py  # 台本生成（Gemini）
│   ├── audio_generator.py   # 音声合成（Gemini TTS、チャンク分割）
│   ├── image_generator.py   # エピソード画像（Gemini Image）
│   ├── markdown_generator.py
│   ├── secure_logging.py    # シークレット流出防止
│   ├── notifiers/slack.py
│   └── storage/
│       ├── gdrive.py
│       └── github_pages.py  # mp3/feed.xml/画像を gh-pages へpush
├── tools/               # テスト用スクリプト
├── assets/              # 番組カバー、エピポード生成リファレンス
├── config.yaml          # 全設定
├── run.sh               # launchdエントリ（git pull → 実行）
└── com.takahiro.ainews.plist  # launchd設定（雛形）
```

## 月額コスト目安

| 項目 | 月額 |
|---|---|
| Gemini API（収集/台本/音声/画像） | $6〜$15 |
| GitHub Pages | $0 |
| Spotify for Creators | $0 |
| Apple Podcasts | $0 |
| Slack | $0 |
| **合計** | **約$6〜$15** |

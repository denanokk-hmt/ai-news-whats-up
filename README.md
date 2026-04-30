# AI Daily What's up

毎朝7時、男女2名のホストがお届けする国内外AIニュースのPodcast自動生成システム。

## 概要

- Gemini 3.1 Pro + Google Search で過去24時間のAIニュースを収集
- 自動翻訳・要約・ジャンル分類
- Gemini 2.5 Native Audio で男女2名の対話形式音声を生成
- Spotify for Podcasters / Apple Podcasts / Amazon Music に自動配信
- Slack通知 + Google Drive保存

## ドキュメント

- [要件定義書](docs/01_requirements.md)
- [設計書](docs/02_design.md)
- [構築タスク手順](docs/03_task_procedure.md)

## セットアップ

詳細は [構築タスク手順](docs/03_task_procedure.md) Phase 0 を参照。

```bash
# 環境構築
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# シークレット設定（ユーザー手動）
cp .env.example .env
# .env を編集して API Key 等を記入

# 実行
python -m src.main
```

## 構成

```
ai-news-whats-up/
├── docs/         # 設計ドキュメント
├── src/          # ソースコード
├── data/         # SQLite (重複排除用)
├── output/       # 日次出力（mp3, md, json）
└── podcast/      # GitHub Pages配信用（別管理）
```

# システム構成図

最終更新: 2026-05-04

## 全体構成

```
┌────────────────────────────────────────────────────────────────────┐
│  Mac Mini（hmt） — 本番運用ホスト                                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ launchd (daily 07:00 JST)                                    │  │
│  │     │                                                         │  │
│  │     ▼                                                         │  │
│  │ run.sh: git pull → pip install -e . → python -m src.main     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│     │                                                               │
│     ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ src/main.py パイプライン                                       │  │
│  │  1. collector       → Gemini 3.1 Pro + Google Search          │  │
│  │  2. dedup           → SQLite（過去30日のURLハッシュ照合）       │  │
│  │  3. script_generator → Gemini 3.1 Pro（敬語/日付/禁止語尾チェック）│
│  │  4. audio_generator → Gemini 3.1 Flash TTS                    │  │
│  │       - 10行ごとにチャンク分割合成                              │  │
│  │       - tempo=1.10x, pitch=0.92x                              │  │
│  │       - ffmpeg loudnorm（音量正規化）                           │  │
│  │  5. image_generator → Gemini 3.1 Flash Image                  │  │
│  │       - assets/cover.png をベースに当日トピックで編集          │  │
│  │       - Apple要件 3000x3000 / JPG / 500KB以下に最適化         │  │
│  │  6. markdown_generator → digest.md                            │  │
│  │  7. storage.gdrive   → Google Drive アップロード              │  │
│  │  8. storage.github_pages → mp3/画像/feed.xml を gh-pages へpush│  │
│  │  9. notifiers.slack  → Slack Incoming Webhook                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌──────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│ Google Drive │    │ GitHub Pages         │    │ Slack            │
│ - mp3        │    │ (gh-pages branch)    │    │ - 通知           │
│ - digest.md  │    │ - cover.jpg          │    │                  │
│              │    │ - episodes/*.mp3     │    │                  │
│              │    │ - episode_images/*   │    │                  │
│              │    │ - feed.xml ← 番組URL │    │                  │
└──────────────┘    └──────┬───────────────┘    └──────────────────┘
                           │
                           ▼ RSS購読
                  ┌─────────────────────────┐
                  │ Spotify for Creators    │
                  │ → Apple Podcasts        │
                  │ → Amazon Music 等       │
                  └─────────────────────────┘
                           │
                           ▼ 配信
                  ┌─────────────────────────┐
                  │ リスナー（各種Podcast）  │
                  └─────────────────────────┘
```

## データフロー

```
ニュース → 記事JSON → 重複除外 → 台本 → 音声 → エピソード画像
                                    ↓
                              digest.md 生成
                                    ↓
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
       Google Drive          GitHub Pages              Slack通知
       (mp3 + md)         (mp3 + 画像 + feed.xml)
                                    ↓ RSS
                          Spotify/Apple/Amazon
```

## 配信時間軸

```
07:00 JST  launchd 起動
07:00:01   run.sh 実行
07:00:02   git pull
07:00:05   collector 開始（約1.5分）
07:01:30   dedup
07:01:35   script 生成（約1分）
07:02:30   audio 生成（チャンク分割で約3分）
07:05:30   image 生成（約30秒）
07:06:00   markdown 生成
07:06:05   GDrive アップロード
07:06:30   GitHub Pages push
07:06:45   Slack通知
07:07:00   完了

その後：
07:30頃    Slack通知到着確認可能
数時間後    Spotifyが RSS再フェッチ → 新エピソード反映
1日以内    Apple Podcasts に新エピソード反映
```

## ファイル配置

```
Mac Mini: ~/DevDev/ai-news-whats-up/
├── .env                    # シークレット（git管理外）
├── credentials.json        # GDrive OAuth（git管理外）
├── gdrive_token.json       # GDriveトークン（git管理外）
├── config.yaml             # 全設定
├── run.sh                  # 自動実行ラッパー
├── assets/
│   ├── cover.png           # マスター画像（編集ベース）
│   ├── cover.jpg           # 配信用（3000x3000 469KB）
│   └── episode_template.png # エピソード生成リファレンス
├── src/                    # 全モジュール
├── output/YYYY-MM-DD/      # 日次出力（git管理外）
├── data/state.db           # 重複排除用SQLite（git管理外）
└── logs/                   # launchd出力（git管理外）

GitHub: denanokk-hmt/ai-news-whats-up
├── main ブランチ           # ソースコード
└── gh-pages ブランチ       # Podcast配信
    ├── cover.jpg
    ├── feed.xml
    ├── episodes/YYYY-MM-DD.mp3（同日再生成時は -r2 等）
    └── episode_images/YYYY-MM-DD.jpg
```

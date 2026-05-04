# 構築タスク手順: AI What's Up News

最終更新: 2026-04-28

## フェーズ依存関係

```
[Phase 0: 事前準備（ユーザー作業）]
            │
            ├──→ [Phase 1: 収集] ──→ [Phase 2: 重複排除]
            │                              │
            │                              ▼
            │                       [Phase 3: 台本生成]
            │                              │
            │                              ▼
            │                       [Phase 4: 音声生成]
            │                              │
            │       ┌──────────────────────┴────────┐
            │       ▼                               ▼
            │  [Phase 5: Markdown]          [Phase 6: GDrive]
            │       │                               │
            │       └────────┬──────────────────────┘
            │                ▼
            ├────→ [Phase 7: GitHub Pages + RSS]
            │      [Phase 8: Slack]
            │      [Phase 9: launchd]
            │                │
            │                ▼
            └────→ [Phase 10: Spotify登録（ユーザー作業）]
```

---

## Phase 0: ユーザー事前準備

ユーザー作業（Claude実行不可）。以下を全て完了してから先のフェーズに進む。

| No | 項目 | 取得先 | 用途 |
|---|---|---|---|
| ① | GEMINI_API_KEY | Google AI Studio | 収集・台本・音声 |
| ② | Google Drive OAuth Client | Google Cloud Console | GDrive API認証 |
| ③ | GitHub public repo（ai-news-whats-up） | GitHub | Pages配信先 |
| ④ | GitHub Personal Access Token（repo権限） | GitHub | git push用 |
| ⑤ | Slack Incoming Webhook URL | Slack Apps | 通知 |
| ⑥ | Spotify for Podcastersアカウント | Spotify | Podcast配信（Phase 10で使用） |

`.env` への記入はユーザー自身で実施：
```bash
# 例（実値はユーザーが手動入力）
echo 'GEMINI_API_KEY=...' >> .env
echo 'SLACK_WEBHOOK_URL=...' >> .env
echo 'GITHUB_TOKEN=...' >> .env
```

---

## Phase 1: ニュース収集モジュール

**ファイル**: `src/collector.py`

**実装内容**:
- Gemini 3.1 Pro + Google Search grounding
- 過去24時間対象
- 海外記事の日本語翻訳・要約・ジャンル分類・重要度採点
- JSON形式で構造化出力

**検証**:
- 単体実行で `articles.json` が生成される
- 20件前後の記事が日本語要約付きで取得できる
- 各記事に genre, importance が設定されている

**前提**: Phase 0 ① 完了

---

## Phase 2: 重複排除モジュール

**ファイル**: `src/dedup.py`

**実装内容**:
- SQLite (`data/state.db`) に `seen_articles` テーブル
- URL正規化 + SHA256 で照合
- 過去30日内の重複を排除
- 30日超のレコードはパージ

**検証**:
- 同じ記事を2回投入しても2回目は弾かれる
- 30日経過後にレコードが消える

**前提**: Phase 1 完了

---

## Phase 3: 台本生成モジュール

**ファイル**: `src/script_generator.py`

**実装内容**:
- Gemini 3.1 Pro で TAKU(男性)/MIO(女性) の対話台本を生成
- 5-10分（2000-3500字）
- オープニング・本編・クロージング構造
- 出力形式: `TAKU: ...\nMIO: ...`

**検証**:
- `script.txt` が指定文字数範囲で生成される
- 対話の流れが自然
- ニュース内容が正しく反映されている

**前提**: Phase 2 完了

---

## Phase 4: 音声生成モジュール

**ファイル**: `src/audio_generator.py`

**実装内容**:
- `gemini-2.5-flash-preview-native-audio-dialog` 使用
- multi_speaker_voice_config で TAKU/MIO に異なる音声を割当
  - 男性候補: Achernar, Schedar
  - 女性候補: Aoede, Kore
- 出力 WAV を ffmpeg で mp3 に変換

**前提**:
- Phase 3 完了
- ffmpeg インストール: `brew install ffmpeg`

**検証**:
- `episode.mp3` が生成される
- 男女2名の自然な対話として再生できる
- 5-10分の長さ

---

## Phase 5: Markdownダイジェスト生成

**ファイル**: `src/markdown_generator.py`

**実装内容**:
- 設計書セクション3.5のフォーマットに従う
- ジャンル別記事一覧
- 台本全文埋め込み
- Spotify/GDriveリンクのプレースホルダ

**検証**:
- `digest.md` が生成される
- 構造が正しい
- ジャンル別にグルーピングされている

**前提**: Phase 4 完了

---

## Phase 6: Google Drive連携

**ファイル**: `src/storage/gdrive.py`

**実装内容**:
- `google-api-python-client` + `google-auth-oauthlib`
- 初回はブラウザOAuth認証 → `token.json` 保存
- フォルダ構成: `AI What's Up News / YYYY / MM / YYYY-MM-DD/`
- `episode.mp3` と `digest.md` をアップロード
- 共有リンク取得

**検証**:
- GDriveに正しく配置される
- リンクで開ける

**前提**: Phase 0 ② 完了 + Phase 4 完了

---

## Phase 7: GitHub Pages + RSS配信

**ファイル**: `src/storage/github_pages.py`

**実装内容**:
- mp3 を `podcast/episodes/YYYY-MM-DD.mp3` にコピー
- `feed.xml` に新エピソードを追記（既存エピソードは保持）
- iTunes/Spotify互換のRSS仕様（`feedgen` ライブラリ使用）
- git add/commit/push を自動実行

**検証**:
- GitHub Pages のURLでmp3が再生できる
- feed.xml がRSSバリデーション（castfeedvalidator.com 等）を通過

**前提**: Phase 0 ③④ 完了 + Phase 5,6 完了

---

## Phase 8: Slack通知

**ファイル**: `src/notifiers/slack.py`

**実装内容**:
- Slack Block Kit で整形
- ヘッダー + トピック5件 + ボタン2つ（Spotify / GDrive）
- 失敗時通知も実装

**検証**:
- Slackに正しく投稿される
- ボタンリンクが正しい

**前提**: Phase 0 ⑤ 完了 + Phase 5 完了

---

## Phase 9: オーケストレーター + launchd

**ファイル**: `src/main.py` + `com.takahiro.ainews.plist`

**実装内容**:
- `src/main.py` で全フェーズを順次実行
- エラーハンドリング（リトライ、Slack失敗通知）
- `com.takahiro.ainews.plist` で毎朝07:00 JST起動
- `launchctl load ~/Library/LaunchAgents/com.takahiro.ainews.plist` で登録

**検証**:
- 手動実行 (`python -m src.main`) で全工程が完走
- launchd で指定時刻に自動起動

**前提**: Phase 0 ① + Phase 6 完了（Phase 7,8 は失敗してもmain実行は継続する設計）

---

## Phase 10: Spotify for Podcasters 登録（運用作業）

ユーザー作業。

**手順**:
1. https://podcasters.spotify.com にログイン
2. 「Add a podcast」→「I have an existing podcast」
3. RSSフィードURLを入力: `https://USERNAME.github.io/ai-news-whats-up/feed.xml`
4. 認証コードを取得 → `feed.xml` の `<podcast:verify>` タグに追記 → push
5. Spotifyでオーナー確認 → 完了
6. 番組情報・カバー画像を登録
7. Apple Podcasts / Amazon Music への展開設定（Spotify経由で自動展開可能）

これで世界中から購読可能な状態になる。

**前提**: Phase 7 完了 + 初回エピソードがGitHub Pagesに配置済み

---

## 進め方の推奨

1. **Phase 0** のうち API Key 関連を整備（Phase 1〜5 で必要）
2. **Phase 1〜5 を実装・テスト**（Gemini APIだけで動くので並行実装可）
3. その間に Phase 0 の GDrive OAuth、GitHub repo、Slack Webhook を整備
4. **Phase 6〜9 を実装**
5. **Phase 10** はSpotify側の運用作業

各フェーズは独立してテスト可能。途中のフェーズで問題が出ても、その時点までの成果物は使える設計。

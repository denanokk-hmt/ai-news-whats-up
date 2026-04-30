# 要件定義書: AI Daily What's up

最終更新: 2026-04-28

## 1. 背景・目的

国内外のAI関連最新ニュースを毎朝自動で取得・要約し、男女2名のホストによる対話形式のPodcastとして配信するシステムを構築する。複数ユーザーがPodcastを購読することで、移動中・作業中でも国内外のAI動向を音声で把握できる。

## 2. ユースケース

- 毎朝07:00（JST）、自動で前日19:00から当日06:00までのAIニュースを収集
- 海外記事は自動で日本語に翻訳・要約
- ジャンル別に整理
- 男女2名のホストによる5〜10分の対話形式音声を生成
- Spotify for Podcasters経由で Apple Podcasts / Spotify / Amazon Music に配信
- Slackに概要通知（ヘッドライン+リンク）
- 詳細はGoogle Driveに永続保存（Markdown）

## 3. 機能要件

| ID | 要件 | 優先度 |
|---|---|---|
| FR-01 | 国内外AIニュースを網羅的に収集（前日19:00〜当日06:00） | 必須 |
| FR-02 | 海外記事を日本語に翻訳・要約 | 必須 |
| FR-03 | ジャンル別に分類（Geminiが自動判定） | 必須 |
| FR-04 | 男女2人の対話形式台本を自動生成 | 必須 |
| FR-05 | 男女2人の音声で5〜10分のmp3を生成 | 必須 |
| FR-06 | Markdownダイジェストを生成 | 必須 |
| FR-07 | mp3とMarkdownをGoogle Driveに保存 | 必須 |
| FR-08 | Spotify for Podcastersに自動投稿（RSS経由） | 必須 |
| FR-09 | Slackにヘッドライン+要約+Podcastリンクを通知 | 必須 |
| FR-10 | 朝07:00 (JST) に自動実行 | 必須 |
| FR-11 | 過去30日内の重複記事を除外 | 必須 |

## 4. 非機能要件

| 項目 | 内容 |
|---|---|
| コスト | 月額 $0〜数ドル（Gemini API有料契約済み・追加費用最小） |
| 実行環境 | macOS（ユーザーのMac）でローカル実行（launchd） |
| 可用性 | Macスリープ復帰後も実行 |
| 保守性 | 設定はYAML、コードはモジュール分離 |
| セキュリティ | APIキー等のシークレットはローカル`.env`のみで管理、コードや会話に出さない |
| ユーザー数 | 想定5〜10名（Podcast購読者） |

## 5. 確定済み項目

| 項目 | 確定内容 |
|---|---|
| 番組名 | AI Daily What's up |
| 配信頻度 | 1日1本（朝07:00 JST） |
| ニュース取得 | Gemini 3.1 Pro + Google Search grounding |
| 自動翻訳 | 海外記事を日本語化 |
| ジャンル分類 | 自動（Geminiに任せる） |
| 音声生成 | Gemini 2.5 Flash Native Audio |
| 話者構成 | 男女ホスト2名・ポッドキャスト風（対等） |
| エピソード長 | 5〜10分 |
| 配信先 | Spotify for Podcasters（Apple/Spotify/Amazon自動配信） |
| Slack通知 | あり |
| GDrive保存 | Markdown + mp3 |
| Web UI | 不要 |
| スマホプッシュ通知 | 不要（Podcastで代替） |
| 複数ユーザー対応 | Podcast購読で実現 |
| バッチ実行 | ローカルMac（launchd） |
| 重複排除期間 | 30日 |

## 6. スコープ外

- ニュース速報通知（朝1回配信のみ）
- ライブ配信
- リスナーからのフィードバック収集機能

## 7. 制約・前提

- ユーザーはGemini API有料契約済み
- ユーザーはGoogle Driveアカウントを所有
- ユーザーはGitHubアカウントを所有（Public Pages配信用）
- ユーザーはSpotify for Podcastersを利用可能
- VoiceVoxは採用しない（Google Native Audioに統一）

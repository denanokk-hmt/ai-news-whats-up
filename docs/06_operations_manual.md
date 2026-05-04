# 運用手順書

最終更新: 2026-05-04

## 1. 通常運用

毎朝 07:00 JST に Mac Mini で自動配信されます。手動操作は不要です。

| 朝のチェック項目 | 確認場所 |
|---|---|
| Slack に通知が届いているか | Slack |
| Spotify に新エピソードが反映されたか（数時間後） | Spotify番組URL |
| エラーが発生していないか | `~/DevDev/ai-news-whats-up/logs/stderr.log` |

## 2. 手動実行

任意の時刻に実行する場合：

```bash
ssh mac-mini "launchctl start com.hmt.ainews"
# 進捗を見る
ssh mac-mini "tail -f ~/DevDev/ai-news-whats-up/logs/stdout.log"
```

## 3. ログ確認

| ログ | パス（Mac Mini） |
|---|---|
| 標準出力 | `~/DevDev/ai-news-whats-up/logs/stdout.log` |
| エラー | `~/DevDev/ai-news-whats-up/logs/stderr.log` |
| 各日の生成物 | `~/DevDev/ai-news-whats-up/output/YYYY-MM-DD/` |

ログ末尾を取得：

```bash
ssh mac-mini "tail -100 ~/DevDev/ai-news-whats-up/logs/stdout.log"
```

## 4. 設定変更

### 配信時刻を変更したい

Mac Mini の plist を編集：

```bash
ssh mac-mini "vi ~/Library/LaunchAgents/com.hmt.ainews.plist"
# Hour / Minute を変更
ssh mac-mini "launchctl unload ~/Library/LaunchAgents/com.hmt.ainews.plist && launchctl load ~/Library/LaunchAgents/com.hmt.ainews.plist"
```

### 音声・台本のスタイルを変更したい

`config.yaml` または `src/script_generator.py` / `src/audio_generator.py` のプロンプトを編集 → commit & push。
Mac Mini は次回実行時に自動 git pull するので追加操作不要。

### 番組メタ情報を変更したい

`config.yaml` の `podcast` セクションを編集 → commit & push。

## 5. トラブルシューティング

### 5-1. 朝の自動配信が走らなかった

| 原因候補 | 確認・対処 |
|---|---|
| Mac Mini が電源OFF | Mac Mini 起動を確認 |
| launchd が unload されている | `ssh mac-mini "launchctl list \| grep ainews"` で確認、なければ `launchctl load ~/Library/LaunchAgents/com.hmt.ainews.plist` |
| stderr.log にエラー | ログ末尾を確認、原因に応じて対処 |

### 5-2. Gemini API クォータ超過

```
429 RESOURCE_EXHAUSTED
```

→ Tier 1 でも 1日制限がある。Google AI Studio の使用量画面で確認。
   有料化漏れ時は `denkaishitsu-906` プロジェクトに課金アカウントが紐付いているか確認。

### 5-3. GDrive 認証エラー

`gdrive_token.json` の期限切れ or 失効：

```bash
ssh mac-mini "rm ~/DevDev/ai-news-whats-up/gdrive_token.json"
# 次回手動実行時にブラウザOAuthが起動するが、Mac Mini にディスプレイが必要
# → ローカル（MBP）で再認証してから scp で送る方が安全
```

### 5-4. GitHub push 失敗

SSH鍵の期限・権限切れ：

```bash
ssh mac-mini "ssh -T git@github.com"  # 認証確認
```

### 5-5. エピソード再生成（同日の差し替え）

```bash
ssh mac-mini "launchctl start com.hmt.ainews"
```

→ ファイル名が自動的に `-r2`、`-r3` になり旧版は削除される。

### 5-6. 過去エピソードを削除したい

`gh-pages` ブランチで該当mp3と画像を削除 → feed.xml を再生成 → push。

```bash
# 例: 5/3 のエピソード削除
PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
import subprocess, tempfile
from src.config import PROJECT_ROOT, load_config
from src.storage.github_pages import _build_feed
from src.storage.gdrive import get_authenticated_email

config = load_config()
email = get_authenticated_email()
with tempfile.TemporaryDirectory() as tmp:
    clone = Path(tmp) / 'gh-pages'
    subprocess.run(['git', 'clone', '--branch', 'gh-pages', '--single-branch',
                    'git@github.com:denanokk-hmt/ai-news-whats-up.git', str(clone)],
                   cwd=str(PROJECT_ROOT), check=True)
    for f in (clone / 'episodes').glob('2026-05-03*'): f.unlink()
    for f in (clone / 'episode_images').glob('2026-05-03*'): f.unlink()
    feed_xml = _build_feed(config['podcast'], config['storage']['github']['pages_url'],
                           clone / 'episodes', clone / 'episode_images',
                           f\"{config['storage']['github']['pages_url']}/cover.jpg\", email)
    (clone / 'feed.xml').write_text(feed_xml, encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=str(clone), check=True)
    subprocess.run(['git', 'commit', '-m', 'Delete 2026-05-03 episode'], cwd=str(clone), check=True)
    subprocess.run(['git', 'push', 'origin', 'gh-pages'], cwd=str(clone), check=True)
"
```

## 6. メンテナンス

### 6-1. 重複排除DBの肥大化

過去30日のレコードのみ自動的に保持される（コード内で自動削除）。手動操作不要。

### 6-2. 出力ファイルの容量管理

`output/` 配下が増え続ける。月1回程度クリーンアップ：

```bash
ssh mac-mini "find ~/DevDev/ai-news-whats-up/output -type d -mtime +60 -exec rm -rf {} +"
```

### 6-3. GitHub Pages 容量

mp3 が蓄積する。1年で数GB程度。GitHub の上限は 1GB/repo（ソフト）、100GB（ハード）。
過去エピソードを定期的に整理：

```bash
# 90日より古いエピソードを削除（手順は 5-6 を参考）
```

## 7. 配信先の追加

### Apple Podcasts への提出

Phase 10 ガイド参照（`docs/03_task_procedure.md` Phase 10）。

### Amazon Music

`https://podcasters.amazon.com` で同じ RSS URL を提出。

## 8. 緊急停止

配信を一時停止したい場合：

```bash
ssh mac-mini "launchctl unload ~/Library/LaunchAgents/com.hmt.ainews.plist"
```

再開：

```bash
ssh mac-mini "launchctl load ~/Library/LaunchAgents/com.hmt.ainews.plist"
```

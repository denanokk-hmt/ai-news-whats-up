# セットアップ手順書（新環境構築）

最終更新: 2026-05-04

別Mac（または再構築時）で稼働させる手順です。

## 前提

- macOS Apple Silicon（M1以降推奨）
- インターネット接続
- 各種アカウント（GCP, GitHub, Google専用, Slack等）

## 1. 必要ツールのインストール

```bash
# Homebrew インストール
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Apple Silicon の場合 PATH 設定
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# 必要パッケージ
brew install python@3.12 ffmpeg git
```

## 2. SSH鍵の準備（GitHub用）

既存鍵がない場合：

```bash
ssh-keygen -t ed25519 -C "your-email@example.com"
cat ~/.ssh/id_ed25519.pub
# 上記の出力を https://github.com/settings/keys に登録
```

## 3. プロジェクトクローン

```bash
mkdir -p ~/DevDev && cd ~/DevDev
git clone git@github.com:denanokk-hmt/ai-news-whats-up.git
cd ai-news-whats-up
```

## 4. Python 仮想環境

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

## 5. シークレット配置

### 5-1. .env

`.env.example` を参考に `.env` を作成：

```bash
cat > .env <<'EOF'
GEMINI_API_KEY=（Google AI Studio で発行）
SLACK_WEBHOOK_URL=（Slack Apps で発行）
EOF
chmod 600 .env
```

### 5-2. credentials.json（GDrive OAuth）

GCP Console で OAuth Client（Desktop App）をダウンロードし、プロジェクトルートに配置。

```bash
# Downloads から移動
mv ~/Downloads/client_secret_*.json ~/DevDev/ai-news-whats-up/credentials.json
chmod 600 credentials.json
```

### 5-3. gdrive_token.json（初回認証）

```bash
PYTHONPATH=. .venv/bin/python -c "from src.storage.gdrive import _get_credentials; _get_credentials()"
```

ブラウザが開く → 専用アカウントでサインイン → 同意。`gdrive_token.json` が自動生成される。

## 6. 動作確認

依存ロード確認：

```bash
PYTHONPATH=. .venv/bin/python -c "
from src.collector import collect_news
from src.audio_generator import generate_audio
from src.image_generator import generate_episode_image
from src.storage.gdrive import _get_credentials
from src.config import load_config
print('All imports OK')
print('Podcast:', load_config()['podcast']['title'])
"
```

## 7. launchd 設定

```bash
# プロジェクトルートに plist がある（com.takahiro.ainews.plist）
# 自分のユーザー名・パスに合わせて編集

USERNAME=$(whoami)
sed -e "s|/Users/takahiro|/Users/${USERNAME}|g" \
    -e "s|com.takahiro.ainews|com.${USERNAME}.ainews|g" \
    com.takahiro.ainews.plist > ~/Library/LaunchAgents/com.${USERNAME}.ainews.plist

# プログラム引数を run.sh に変更（編集）
# <string>/Users/.../.venv/bin/python</string>
# <string>-m</string>
# <string>src.main</string>
# ↓
# <string>/Users/.../ai-news-whats-up/run.sh</string>

# 登録
launchctl load ~/Library/LaunchAgents/com.${USERNAME}.ainews.plist
launchctl list | grep ainews
```

## 8. 動作テスト

```bash
launchctl start com.${USERNAME}.ainews
tail -f ~/DevDev/ai-news-whats-up/logs/stdout.log
```

完了まで約3〜5分。

## 9. 旧環境停止（既存運用がある場合）

```bash
ssh old-host "launchctl unload ~/Library/LaunchAgents/com.OLDUSER.ainews.plist"
```

## 10. トラブル時のデバッグ

| 症状 | チェック |
|---|---|
| `Module not found` | `pip install -e .` を再実行 |
| `GEMINI_API_KEY not set` | `.env` 配置確認、`load_dotenv` がパスを認識しているか |
| GitHub push 失敗 | `ssh -T git@github.com` で認証確認 |
| GDrive 認証失敗 | `gdrive_token.json` 削除→再OAuth |
| ffmpeg not found | `which ffmpeg`、PATH 確認、`brew reinstall ffmpeg` |

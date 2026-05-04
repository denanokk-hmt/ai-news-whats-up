#!/bin/bash
# launchd から呼ばれるエントリーポイント。
# 最新コードに更新してから本体を実行する。
set -e
cd "$(dirname "$0")"

# 最新コード取得（失敗しても続行）
git pull --rebase --autostash origin main 2>&1 || echo "git pull failed, continuing with current code"

# 依存更新（pyproject.toml が変わっていれば反映）
.venv/bin/pip install -e . --quiet 2>&1 | tail -3 || true

# 本体実行
exec .venv/bin/python -m src.main

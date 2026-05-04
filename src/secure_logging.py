from __future__ import annotations

import logging
import re

# 機密情報を含むURLパターン（ホスト＋パストークン埋め込み型）
SECRET_URL_PATTERNS = [
    # Slack Webhook
    re.compile(r"https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+"),
    # Discord Webhook
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
    # Generic webhook tokens (path containing >20 char tokens)
    re.compile(r"https://[^/\s]+/[^?\s]*[A-Za-z0-9_-]{30,}[^?\s]*"),
]

# Authorization ヘッダ・Bearer Token
SECRET_HEADER_PATTERNS = [
    re.compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"(api[-_]?key[\"'\s:=]+)[A-Za-z0-9._-]{20,}", re.IGNORECASE),
    re.compile(r"(token[\"'\s:=]+)[A-Za-z0-9._-]{20,}", re.IGNORECASE),
]


def sanitize(text: str) -> str:
    """テキストからURL・トークンを ***REDACTED*** に置換。"""
    if not isinstance(text, str):
        text = str(text)
    for pattern in SECRET_URL_PATTERNS:
        text = pattern.sub("***REDACTED_URL***", text)
    for pattern in SECRET_HEADER_PATTERNS:
        text = pattern.sub(r"\1***REDACTED***", text)
    return text


def configure_logging(level: int = logging.INFO) -> None:
    """全アプリ共通ロギング設定。HTTPライブラリ系のINFOログ（URL含む）を抑制。"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    # URL情報を含む可能性のあるロガーを抑制
    for noisy in [
        "httpx",
        "httpcore",
        "urllib3",
        "requests",
        "googleapiclient.discovery_cache",
        "googleapiclient.discovery",
        "google_genai",
        "google.auth",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


class SanitizingHandler(logging.Handler):
    """ログ出力前にメッセージをsanitize するラッパー。"""

    def __init__(self, target: logging.Handler):
        super().__init__()
        self.target = target

    def emit(self, record: logging.LogRecord) -> None:
        record.msg = sanitize(record.getMessage())
        record.args = ()
        self.target.emit(record)


def install_sanitizing_root_handler() -> None:
    """ルートロガーのStreamHandlerに sanitize ラッパーを被せる。
    既存ハンドラを保持しつつ、出力前にURLパターンをマスクする。
    """
    root = logging.getLogger()
    new_handlers = []
    for h in root.handlers:
        if isinstance(h, SanitizingHandler):
            new_handlers.append(h)
        else:
            new_handlers.append(SanitizingHandler(h))
    root.handlers = new_handlers

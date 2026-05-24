from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# 一時的なネットワーク例外（接続リセット・タイムアウト・サーバ切断・プロキシ障害）。
# google.genai は内部で httpx を使うため、これらが直接伝播してくる。
# LocalProtocolError / UnsupportedProtocol / InvalidURL 等の決定的エラーは含めない。
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.NetworkError,        # ConnectError / ReadError / WriteError / CloseError
    httpx.TimeoutException,    # ConnectTimeout / ReadTimeout / WriteTimeout / PoolTimeout
    httpx.RemoteProtocolError,  # サーバがレスポンス完了前に切断
    httpx.ProxyError,
)

# 例外が別の型にラップされた場合の保険（メッセージ全体を小文字で部分一致）。
_RETRYABLE_KEYWORDS: tuple[str, ...] = (
    "connection reset",
    "connection aborted",
    "connection refused",
    "server disconnected",
    "remoteprotocolerror",
    "readerror",
    "read timed out",
    "readtimeout",
    "connecterror",
    "broken pipe",
    "errno 54",
    "temporarily unavailable",
)


def _is_retryable(e: Exception, retryable_codes: tuple[int, ...]) -> bool:
    if isinstance(e, _RETRYABLE_EXCEPTIONS):
        return True
    msg = str(e)
    # google.genai のステータスエラーは "503 UNAVAILABLE" のように先頭にコードを含む
    if any(f"{code}" in msg[:50] for code in retryable_codes):
        return True
    low = msg.lower()
    return any(kw in low for kw in _RETRYABLE_KEYWORDS)


def with_retry(
    func: Callable[..., Any],
    *args,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    retryable_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    **kwargs,
) -> Any:
    """Gemini API の一時的エラー（HTTP 4xx/5xx・ネットワーク例外）で指数バックオフリトライ。

    遅延: base_delay * 2^(attempt-1)
      attempt 1 失敗→ 2秒待機
      attempt 2 失敗→ 4秒待機
      attempt 3 失敗→ 8秒待機
      attempt 4 失敗→ 16秒待機
      attempt 5 失敗→ raise

    リトライ対象:
      - HTTP ステータス 429/500/502/503/504（メッセージ先頭に含まれる）
      - httpx のネットワーク例外（接続リセット・タイムアウト・サーバ切断）
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if not _is_retryable(e, retryable_codes):
                raise
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini API error (attempt %d/%d): %s: %s | retry in %.1fs",
                    attempt, max_attempts, type(e).__name__, str(e)[:120], delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Gemini API failed after %d attempts: %s: %s",
                    max_attempts, type(e).__name__, str(e)[:200],
                )
    assert last_error is not None
    raise last_error

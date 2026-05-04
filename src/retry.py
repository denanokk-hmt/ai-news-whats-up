from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def with_retry(
    func: Callable[..., Any],
    *args,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    retryable_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    **kwargs,
) -> Any:
    """Gemini API の一時的エラーで指数バックオフリトライ。

    遅延: base_delay * 2^(attempt-1)
      attempt 1 失敗→ 2秒待機
      attempt 2 失敗→ 4秒待機
      attempt 3 失敗→ 8秒待機
      attempt 4 失敗→ 16秒待機
      attempt 5 失敗→ raise
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            # google.genai のエラーは "503 UNAVAILABLE" のような形式で先頭にステータスを含む
            is_retryable = any(f"{code}" in msg[:50] for code in retryable_codes)
            if not is_retryable:
                raise
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini API error (attempt %d/%d): %s | retry in %.1fs",
                    attempt, max_attempts, msg[:120], delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Gemini API failed after %d attempts: %s",
                    max_attempts, msg[:200],
                )
    assert last_error is not None
    raise last_error

from __future__ import annotations

import logging
import socket
import time

logger = logging.getLogger(__name__)

# Gemini API のエンドポイント。DNS 解決＋TCP接続で疎通確認する
# （起床直後は WiFi/DNS 復帰前のため、ここでリトライ待機する）。
DEFAULT_HOST = "generativelanguage.googleapis.com"
DEFAULT_PORT = 443


def wait_for_network(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    max_wait: float = 300.0,
    interval: float = 5.0,
    connect_timeout: float = 5.0,
) -> None:
    """ネットワーク疎通（DNS解決＋TCP接続）が確立するまで待機する。

    ラップトップ起床直後は WiFi/DNS 復帰前のことがあり、即座に Gemini へ
    接続すると Connection reset / DNS失敗（nodename nor servname）で落ちる。
    本関数で疎通確立を待ってから本処理へ進む。

    max_wait 秒以内に疎通しなければ RuntimeError を送出する。
    """
    deadline = time.monotonic() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                if attempt > 1:
                    logger.info("Network ready after %d attempt(s)", attempt)
                return
        except OSError as e:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Network not ready after {max_wait:.0f}s "
                    f"(last error: {type(e).__name__}: {e})"
                ) from e
            logger.warning(
                "Network not ready (attempt %d): %s: %s | retry in %.0fs (%.0fs left)",
                attempt, type(e).__name__, e, interval, remaining,
            )
            time.sleep(min(interval, max(0.0, remaining)))
